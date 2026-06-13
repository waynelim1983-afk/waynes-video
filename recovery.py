"""
recovery.py — 自動恢復未完成工作
=================================================
功能：
  1. 掃描 Google Flow 畫廊，下載尚未下載的生成影片
  2. 掃描 clips/ 資料夾，找出未入佇列的 .mp4
  3. 對未入佇列的影片補建 metadata、寫入 upload_queue.json
  4. 自動觸發 YouTube 上傳

執行：
  python recovery.py              # 掃描 + 執行全部恢復
  python recovery.py --scan-only  # 只列報告，不執行
  python recovery.py --no-flow    # 跳過 Flow 掃描（只補 clips 資料夾）
  python recovery.py --no-upload  # 補齊 queue 後不上傳
"""

import sys
import re
import json
import time
import logging
import argparse
import datetime
import subprocess
import urllib.request
from pathlib import Path

BASE_DIR   = Path(r"C:\projects\YT\amazon")
CLIPS_DIR  = BASE_DIR / "output" / "clips"
QUEUE_FILE = BASE_DIR / "output" / "upload_queue.json"
CONFIG_FILE = BASE_DIR / "config" / "flow_config.json"
LOG_FILE   = BASE_DIR / "logs" / "daily.log"
MIN_SIZE   = 200_000   # 200 KB — 有效影片最小尺寸

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RECOVERY] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(open(sys.stdout.fileno(), mode="w",
                                   encoding="utf-8", errors="replace",
                                   closefd=False)),
    ],
)
log = logging.getLogger(__name__)

sys.path.insert(0, str(BASE_DIR))


# ══════════════════════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════════════════════

def _load_queue() -> list:
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text("utf-8"))
        except Exception:
            return []
    return []


def _save_queue(queue: list):
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), "utf-8")


def _load_flow_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {}


def _save_flow_config(cfg: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")


def _queued_files(queue: list) -> set:
    """回傳 queue 中所有影片檔名（不含路徑）的集合。"""
    return {Path(e["file"]).name for e in queue if e.get("file")}


# ══════════════════════════════════════════════════════════════
# STEP 1 — clips 資料夾審計
# ══════════════════════════════════════════════════════════════

def audit_clips_folder() -> list[Path]:
    """
    找出 clips/ 中所有 .mp4（>= 200KB）但不在 upload_queue.json 裡的檔案。
    回傳待補入佇列的檔案列表（按修改時間排序）。
    """
    queue = _load_queue()
    queued = _queued_files(queue)

    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    orphans = []
    for f in sorted(CLIPS_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime):
        if f.stat().st_size < MIN_SIZE:
            log.debug(f"  跳過小檔案（{f.stat().st_size // 1024} KB）: {f.name}")
            continue
        if f.name not in queued:
            orphans.append(f)
            log.info(f"  [clips] 未入佇列: {f.name} ({f.stat().st_size // 1024} KB)")

    log.info(f"clips 審計完成：{len(orphans)} 個未入佇列影片")
    return orphans


# ══════════════════════════════════════════════════════════════
# STEP 2 — 根據檔名反推 metadata 並補入佇列
# ══════════════════════════════════════════════════════════════

_TITLE_TEMPLATES = {
    "litter_box": [
        "No More Scooping! This Litter Box Cleans ITSELF 😱 #Shorts",
        "My Cat's Litter Box Cleans Itself — Zero Effort 🤖 #SmartCatLife",
        "This Self-Cleaning Litter Box Changed Everything 🐾 #Shorts",
    ],
    "smart_feeder": [
        "My Cat Gets Fed Automatically — I Did Nothing 🤖 #Shorts",
        "Smart Feeder Feeds My Cat on Schedule 🍚 #SmartPet #Shorts",
        "This Auto Feeder Has My Cat OBSESSED 😂 #CatLife #Shorts",
    ],
    "water_fountain": [
        "Why Cats LOVE Running Water 💧 Smart Fountain #Shorts",
        "This Fountain Made My Cat Drink 3x More Water 😻 #Shorts",
        "Best Gift For Your Cat? This Water Fountain 💧 #Shorts",
    ],
    "pet_camera": [
        "Catching My Cat's Secret Life On Camera 📷 #Shorts",
        "This Pet Camera Tossed a Treat Automatically 🤯 #Shorts",
        "My Cat Waved at the Camera 😂 #SmartHome #Shorts",
    ],
    "gps_tracker": [
        "I Know Exactly Where My Cat Is 24/7 📍 #Shorts",
        "GPS Tracker Saved My Cat — True Story 🐾 #Shorts",
        "Never Lose Your Cat Again 🗺️ GPS Collar #Shorts",
    ],
    "smart_pet": [
        "Smart Gadgets That Actually Help Your Cat 🤖🐱 #Shorts",
        "My Cat Lives Better Than Me 👑 #SmartCatLife #Shorts",
    ],
}


def _rebuild_entry_from_clip(clip_path: Path) -> dict:
    """
    由 clips 檔名（smartcat_YYYY-MM-DD_N_HHMMSS.mp4）反推產品 metadata。
    若解析失敗，以今日產品代替。
    """
    import random as _rand
    from affiliate_products import get_product_from_weekly, build_description

    # 解析檔名：smartcat_2026-05-13_1_101447.mp4
    m = re.match(r"smartcat_(\d{4}-\d{2}-\d{2})_(\d+)_(\d+)\.mp4", clip_path.name)
    if m:
        date_str = m.group(1)
        idx      = int(m.group(2))   # 第幾支（1-based）
        try:
            clip_date   = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            today       = datetime.datetime.now()
            day_offset  = (clip_date - today).days   # 負數 = 過去
            product     = get_product_from_weekly(day_offset=day_offset)
            day_seed    = clip_date.strftime("%Y%m%d")
        except Exception:
            product  = get_product_from_weekly()
            day_seed = datetime.datetime.now().strftime("%Y%m%d")
            idx      = 1
    else:
        product  = get_product_from_weekly()
        day_seed = datetime.datetime.now().strftime("%Y%m%d")
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        idx      = 1

    category = product.get("category", "smart_pet")
    templates = _TITLE_TEMPLATES.get(category, _TITLE_TEMPLATES["smart_pet"])
    _rand.seed(day_seed + str(idx) + category)
    title = _rand.choice(templates)
    desc  = build_description(product)

    entry_id = f"smartcat_{date_str}_{idx}"
    # 若 id 衝突（同天同 idx），附加時間戳
    queue = _load_queue()
    existing_ids = {e["id"] for e in queue}
    if entry_id in existing_ids:
        ts_suffix = clip_path.stem.split("_")[-1]
        entry_id  = f"{entry_id}_{ts_suffix}"

    return {
        "id":          entry_id,
        "queued_at":   datetime.datetime.now().isoformat(),
        "status":      "pending",
        "file":        str(clip_path),
        "title":       title,
        "description": desc,
        "tags":        ["SmartCatLife", "PetTech", "CatGadgets", "SmartPet",
                        "CatMom", "CatDad", "AutomaticLitterBox", "Shorts"],
        "product":     product["name"],
        "asin":        product["asin"],
        "recovered":   True,   # 標記為 recovery 補入
    }


def queue_orphan_clips(orphans: list[Path]) -> int:
    """將未入佇列的影片補入 upload_queue.json，回傳補入數量。"""
    if not orphans:
        return 0
    queue = _load_queue()
    added = 0
    for clip in orphans:
        entry = _rebuild_entry_from_clip(clip)
        queue.append(entry)
        added += 1
        log.info(f"  補入佇列: {entry['id']} | {entry['title'][:45]}")
    _save_queue(queue)
    log.info(f"已補入 {added} 支影片至 upload_queue.json")
    return added


# ══════════════════════════════════════════════════════════════
# STEP 3 — Flow 畫廊掃描 + 下載
# ══════════════════════════════════════════════════════════════

def _extract_clip_uuid(url: str) -> str | None:
    """從 flow-content URL 提取 video UUID（用作下載追蹤 ID）。"""
    m = re.search(r"flow-content\.google/(?:video|media)/([a-zA-Z0-9_\-]+)", url)
    return m.group(1) if m else None


def _download_url_to_file(url: str, dest: Path, cookies: dict = None) -> bool:
    """用 urllib 下載影片 URL 到 dest。"""
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent",
                       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/124 Safari/537.36")
        if cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
            req.add_header("Cookie", cookie_str)
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        if len(data) < MIN_SIZE:
            log.warning(f"  下載太小（{len(data)//1024} KB），跳過")
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        log.info(f"  ✓ 下載完成 ({len(data)//1024} KB) → {dest.name}")
        return True
    except Exception as e:
        log.error(f"  下載失敗: {e}")
        return False


def scan_flow_and_download(scan_only: bool = False) -> list[Path]:
    """
    開啟 Flow 畫廊，找出未下載的生成影片並下載之。
    回傳新下載的檔案路徑列表。
    使用 flow_config.json → "downloaded_clip_uuids" 追蹤已下載的 UUID。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("playwright 未安裝，跳過 Flow 掃描")
        return []

    cfg = _load_flow_config()
    downloaded_uuids: set = set(cfg.get("downloaded_clip_uuids", []))
    log.info(f"Flow 掃描開始 | 已知已下載 UUID: {len(downloaded_uuids)} 個")

    new_files = []

    with sync_playwright() as pw:
        from veo3_browser import get_context, _is_logged_in, _navigate_to_flow

        _, ctx = get_context(pw, headless=False)
        page = ctx.new_page()

        # ── 進入 Flow project ──────────────────────────────
        if not _navigate_to_flow(page):
            log.error("無法進入 Flow，跳過掃描")
            ctx.close()
            return []

        if not _is_logged_in(page):
            log.error("Flow 未登入，請先執行: python veo3_browser.py --login-only")
            ctx.close()
            return []

        time.sleep(3)
        log.info("  ✓ 已進入 Flow project，掃描畫廊...")

        # ── 枚舉畫廊縮圖 ─────────────────────────────────
        # Flow 畫廊通常在 project 左側面板，每個 clip 是一個小卡片
        # 用 JS 找所有符合「小尺寸、非底部工具列」的可點擊縮圖
        page.screenshot(path=str(BASE_DIR / "logs" / "flow_gallery_scan.png"))

        gallery_items = page.evaluate("""
            () => {
                // 找可能是 clip 縮圖的元素：有 src 的 img / video poster，
                // 且位於頁面左半側（x < 400）或頂部縮圖列（y < 300）
                const candidates = [];
                const viewport = { w: window.innerWidth, h: window.innerHeight };

                // 方法 1：找所有 img 縮圖（in left panel or gallery strip）
                document.querySelectorAll('img').forEach(img => {
                    const r = img.getBoundingClientRect();
                    const src = img.src || img.currentSrc || '';
                    if (r.width < 20 || r.height < 20) return;   // icon 不要
                    if (r.width > 600) return;                    // 主預覽區不要
                    // flow-content thumbnail 或左側面板
                    if (src.includes('flow-content') ||
                        src.includes('lh3.google') ||
                        r.x < 300 ||
                        (r.y < 400 && r.width < 300)) {
                        candidates.push({
                            type: 'img',
                            x: Math.round(r.x + r.width/2),
                            y: Math.round(r.y + r.height/2),
                            w: Math.round(r.width),
                            h: Math.round(r.height),
                            src: src.slice(0, 100)
                        });
                    }
                });

                // 方法 2：找 data-clip-id / data-asset-id 屬性的元素
                document.querySelectorAll('[data-clip-id], [data-asset-id], [data-id]')
                    .forEach(el => {
                        const r = el.getBoundingClientRect();
                        if (r.width < 10 || r.height < 10) return;
                        candidates.push({
                            type: 'data-attr',
                            x: Math.round(r.x + r.width/2),
                            y: Math.round(r.y + r.height/2),
                            w: Math.round(r.width),
                            h: Math.round(r.height),
                            src: (el.getAttribute('data-clip-id') ||
                                  el.getAttribute('data-asset-id') ||
                                  el.getAttribute('data-id') || '').slice(0, 60)
                        });
                    });

                // 去重（同位置）
                const seen = new Set();
                return candidates.filter(c => {
                    const key = `${Math.round(c.x/10)},${Math.round(c.y/10)}`;
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                }).slice(0, 30);  // 最多掃 30 個縮圖
            }
        """)

        log.info(f"  找到 {len(gallery_items)} 個候選縮圖")
        if not gallery_items:
            log.warning("  找不到縮圖，Flow 畫廊可能為空或版面不符預期（截圖: flow_gallery_scan.png）")
            ctx.close()
            return []

        # ── 對每個縮圖，點擊並嘗試捕獲影片 URL ──────────
        for item_idx, item in enumerate(gallery_items):
            log.info(f"  [縮圖 {item_idx+1}/{len(gallery_items)}] "
                     f"pos=({item['x']},{item['y']}) size={item['w']}x{item['h']}")

            # 設定網路攔截
            captured = []
            def _on_resp(resp, _cap=captured):
                try:
                    url = resp.url
                    ct  = resp.headers.get("content-type", "")
                    if "gstatic" in url:
                        return
                    if ("flow-content.google" in url or "video" in ct or
                            ".mp4" in url):
                        if url not in [u for u, _ in _cap]:
                            _cap.append((url, ct))
                except Exception:
                    pass
            page.on("response", _on_resp)

            # 點擊縮圖
            try:
                page.mouse.click(item["x"], item["y"])
            except Exception as e:
                log.debug(f"  點擊失敗: {e}")
                page.remove_listener("response", _on_resp)
                continue

            # 等待網路回應（最多 8 秒）
            for _ in range(8):
                time.sleep(1)
                if captured:
                    break

            # 也從 Performance API 補撈
            try:
                perf_urls = page.evaluate("""
                    () => performance.getEntriesByType('resource')
                        .map(e => e.name)
                        .filter(u => u.includes('flow-content.google') &&
                                     !u.includes('gstatic') &&
                                     (u.includes('/video/') || u.includes('/media/')))
                """)
                for pu in perf_urls:
                    if pu not in [u for u, _ in captured]:
                        captured.append((pu, "video/mp4"))
            except Exception:
                pass

            page.remove_listener("response", _on_resp)

            if not captured:
                log.info(f"    → 無影片 URL（可能是圖片縮圖或 UI 元素）")
                page.keyboard.press("Escape")
                time.sleep(0.5)
                continue

            # ── 篩選影片 URL（排除縮圖 image）──────────────
            video_urls = [
                (u, ct) for u, ct in captured
                if ("video" in ct or ".mp4" in u or
                    re.search(r"/video/[a-zA-Z0-9_\-]{8,}", u))
                and "image" not in ct
            ]
            if not video_urls:
                log.info(f"    → 只有縮圖 URL，跳過")
                page.keyboard.press("Escape")
                time.sleep(0.5)
                continue

            # 取第一個有效影片 URL
            video_url, _ = video_urls[0]
            uuid = _extract_clip_uuid(video_url)
            log.info(f"    影片 URL: {video_url[:70]} | UUID: {uuid}")

            if uuid and uuid in downloaded_uuids:
                log.info(f"    → 已下載（UUID 在追蹤清單），跳過")
                page.keyboard.press("Escape")
                time.sleep(0.5)
                continue

            if scan_only:
                log.info(f"    → [scan-only] 發現未下載影片（UUID: {uuid}）")
                page.keyboard.press("Escape")
                time.sleep(0.5)
                continue

            # ── 取得 cookie（供 urllib 下載簽名 URL）────────
            try:
                cookies = {c["name"]: c["value"] for c in ctx.cookies()
                           if "google" in (c.get("domain") or "")}
            except Exception:
                cookies = {}

            # ── 命名並下載 ───────────────────────────────
            ts        = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
            dest_name = f"smartcat_{ts}_flow_{item_idx+1}.mp4"
            dest_path = CLIPS_DIR / dest_name
            CLIPS_DIR.mkdir(parents=True, exist_ok=True)

            ok = _download_url_to_file(video_url, dest_path, cookies)
            if ok:
                new_files.append(dest_path)
                if uuid:
                    downloaded_uuids.add(uuid)
                    cfg["downloaded_clip_uuids"] = sorted(downloaded_uuids)
                    _save_flow_config(cfg)
                    log.info(f"    UUID {uuid} 已記入追蹤清單")
            else:
                log.warning(f"    下載失敗，跳過此 clip")

            page.keyboard.press("Escape")
            time.sleep(1)

        ctx.close()

    log.info(f"Flow 掃描完成：新下載 {len(new_files)} 支影片")
    return new_files


# ══════════════════════════════════════════════════════════════
# STEP 4 — 觸發 YouTube 上傳
# ══════════════════════════════════════════════════════════════

def trigger_upload():
    """呼叫 youtube_upload.py 處理所有 pending 項目。"""
    uploader = BASE_DIR / "youtube_upload.py"
    if not uploader.exists():
        log.error("youtube_upload.py 不存在")
        return False
    log.info("呼叫 youtube_upload.py...")
    result = subprocess.run(
        [sys.executable, str(uploader)],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            log.info(f"  [upload] {line}")
    if result.returncode != 0 and result.stderr:
        for line in result.stderr.strip().splitlines()[-10:]:
            log.warning(f"  [upload] {line}")
    return result.returncode == 0


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════

def recover_all(scan_only: bool = False, no_flow: bool = False,
                no_upload: bool = False):
    log.info("=" * 60)
    log.info(f"Recovery 開始 | {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    log.info(f"  scan_only={scan_only}  no_flow={no_flow}  no_upload={no_upload}")
    log.info("=" * 60)

    newly_downloaded: list[Path] = []

    # ── Step 1: Flow 畫廊掃描 ─────────────────────────────
    if not no_flow:
        log.info("\n[Step 1] Flow 畫廊掃描...")
        try:
            newly_downloaded = scan_flow_and_download(scan_only=scan_only)
        except Exception as e:
            log.error(f"Flow 掃描出錯: {e}")
    else:
        log.info("[Step 1] 已跳過 Flow 掃描（--no-flow）")

    # ── Step 2: clips 資料夾審計 ─────────────────────────
    log.info("\n[Step 2] clips 資料夾審計...")
    orphans = audit_clips_folder()

    # 剛從 Flow 下載的也可能還未入佇列
    for nf in newly_downloaded:
        if nf not in orphans and nf.exists() and nf.stat().st_size >= MIN_SIZE:
            queue = _load_queue()
            if nf.name not in _queued_files(queue):
                orphans.append(nf)

    # ── Step 3: 補入佇列 ──────────────────────────────────
    if orphans:
        log.info(f"\n[Step 3] 補入 {len(orphans)} 支影片至佇列...")
        if not scan_only:
            queue_orphan_clips(orphans)
        else:
            for f in orphans:
                log.info(f"  [scan-only] 待補入: {f.name}")
    else:
        log.info("[Step 3] 無需補入（所有 clips 已在佇列）")

    # ── Step 4: 上傳 ──────────────────────────────────────
    if not scan_only and not no_upload:
        queue = _load_queue()
        pending = [e for e in queue if e.get("status") == "pending"]
        if pending:
            log.info(f"\n[Step 4] 上傳 {len(pending)} 支 pending 影片...")
            trigger_upload()
        else:
            log.info("[Step 4] 無 pending 項目，跳過上傳")
    elif scan_only:
        log.info("[Step 4] scan-only 模式，跳過上傳")
    else:
        log.info("[Step 4] --no-upload，跳過上傳")

    # ── 摘要 ──────────────────────────────────────────────
    queue = _load_queue()
    total     = len(queue)
    uploaded  = sum(1 for e in queue if e.get("status") == "uploaded")
    pending   = sum(1 for e in queue if e.get("status") == "pending")
    failed    = sum(1 for e in queue if e.get("status") == "failed")
    recovered = sum(1 for e in queue if e.get("recovered"))

    log.info("\n" + "=" * 60)
    log.info(f"Recovery 完成摘要:")
    log.info(f"  Flow 新下載  : {len(newly_downloaded)} 支")
    log.info(f"  clips 補入   : {len(orphans)} 支")
    log.info(f"  佇列總計     : {total} 支（已上傳 {uploaded} / pending {pending} / 失敗 {failed}）")
    log.info(f"  recovery 標記: {recovered} 支")
    log.info("=" * 60)


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smart Cat Slave — 自動恢復工具")
    parser.add_argument("--scan-only",  action="store_true", help="只掃描報告，不執行任何動作")
    parser.add_argument("--no-flow",    action="store_true", help="跳過 Flow 畫廊掃描")
    parser.add_argument("--no-upload",  action="store_true", help="補齊 queue 後不觸發上傳")
    args = parser.parse_args()

    recover_all(
        scan_only=args.scan_only,
        no_flow=args.no_flow,
        no_upload=args.no_upload,
    )
