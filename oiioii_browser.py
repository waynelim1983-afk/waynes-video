"""
oiioii_browser.py — 用 Playwright 操作 oiioii.ai 生成影片（OiiOii 備援）

  - 使用 Seedance 2.0 Pro 模型
  - 需要 OiiOii 帳號（新帳號有 2000 FREE tokens）
  - 規格：9:16 垂直，720p，~6 秒
  - UI 為 tldraw canvas，主要用座標點擊（viewport: 1568×708）
  - 重要：prompt 不能有換行（會自動送出），已自動過濾

座標基準（來源：ai-media-generator site-profiles/oiioii.md）：
  viewport: 1568×708（啟動時固定此尺寸）

首次執行前需登入：
  python oiioii_browser.py --login-only

正常生影：
  python oiioii_browser.py --prompt "..." --output "C:\\YT\\amazon\\output\\clips\\xxx.mp4"
"""

import sys
import re
import time
import base64
import argparse
import logging
import urllib.request
from pathlib import Path

from prompt_validator import validate_prompt

BASE_DIR       = Path(r"C:\projects\YT\amazon")
LOG_FILE       = BASE_DIR / "logs" / "daily.log"
CHROME_PROFILE = BASE_DIR / "config" / "chrome_profile_oiioii"

OIIOII_URL = "https://www.oiioii.ai/"

# viewport 必須固定，tldraw canvas 座標依此計算
VIEWPORT_W = 1568
VIEWPORT_H = 708

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [OIIOII] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w",
                 encoding="utf-8", errors="replace", closefd=False)
        ),
    ],
)
log = logging.getLogger(__name__)


# ── Chrome Context ─────────────────────────────────────────────

def get_context(pw, headless: bool = False):
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(CHROME_PROFILE),
        channel="chrome",
        headless=headless,
        slow_mo=80,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-extensions",
            "--disable-sync",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        accept_downloads=True,
        viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
        ignore_default_args=["--enable-automation"],
    )


# ── 登入確認 ────────────────────────────────────────────────────

def _is_logged_in(page) -> bool:
    try:
        url = page.url
        if "login" in url or "signin" in url:
            return False
        # URL 包含 /home 或 /space 代表已登入
        if "/home" in url or "/space" in url:
            return True
        checks = [
            # 中文介面
            page.locator('text="自由畫布"').count(),
            page.locator('text="劇情故事短片"').count(),
            page.locator('text="我的資產"').count(),
            page.locator('text="加入宣傳委員"').count(),
            # 英文介面 fallback
            page.locator('text="Free Canvas"').count(),
            page.locator('text="New Project"').count(),
            # token 數字顯示（右上角）
            page.locator('[class*="credit" i]').count(),
            page.locator('[class*="balance" i]').count(),
        ]
        return any(c > 0 for c in checks)
    except Exception:
        return False


def wait_for_login(page, timeout_s: int = 300) -> bool:
    log.info("=" * 50)
    log.info("請在瀏覽器視窗中登入 OiiOii 帳號")
    log.info("支援 Google / Email 登入")
    log.info("登入後程式會自動偵測並繼續...")
    log.info("=" * 50)
    for i in range(timeout_s // 3):
        time.sleep(3)
        if _is_logged_in(page):
            log.info(f"  ✓ 偵測到登入成功（等待 {(i + 1) * 3}s）")
            return True
        if i % 10 == 9:
            log.info(f"  等待中... ({(i + 1) * 3}s / {timeout_s}s)")
    log.error("登入逾時")
    return False


# ── 影片下載工具 ─────────────────────────────────────────────────

def _download_http(url: str, output_path: Path) -> bool:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            output_path.write_bytes(resp.read())
        size = output_path.stat().st_size
        if size < 100_000:
            log.warning(f"  下載檔案過小 ({size} bytes)")
            return False
        log.info(f"  ✓ HTTP 下載完成 ({size // 1024} KB) → {output_path.name}")
        return True
    except Exception as e:
        log.error(f"  HTTP 下載失敗: {e}")
        return False


def _download_blob(blob_url: str, output_path: Path, page) -> bool:
    try:
        b64: str = page.evaluate(
            """async (url) => {
                const resp = await fetch(url);
                const buf  = await resp.arrayBuffer();
                const bytes = new Uint8Array(buf);
                let binary = '';
                const chunk = 8192;
                for (let i = 0; i < bytes.length; i += chunk)
                    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
                return btoa(binary);
            }""",
            blob_url,
        )
        if not b64:
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(b64))
        size = output_path.stat().st_size
        if size < 100_000:
            return False
        log.info(f"  ✓ blob 下載完成 ({size // 1024} KB)")
        return True
    except Exception as e:
        log.error(f"  blob 下載失敗: {e}")
        return False


# ── 主要生成流程 ─────────────────────────────────────────────────

def generate(prompt: str, output_path: Path, page) -> bool:
    """
    在已登入的 oiioii.ai 頁面生成影片。
    使用 Free Canvas 模式 + Seedance 2.0 Pro。
    """
    prompt = validate_prompt("oiioii", prompt)
    # OiiOii 不允許 prompt 有換行（會自動送出）
    prompt = prompt.replace("\n", " ").replace("\r", " ").strip()
    log.info(f"OiiOii 生影 | prompt={prompt[:60]}...")

    ss_dir = BASE_DIR / "logs" / "screenshots"
    ss_dir.mkdir(parents=True, exist_ok=True)

    def _ss(name: str):
        try:
            ts = time.strftime("%H%M%S")
            page.screenshot(path=str(ss_dir / f"oiioii_{ts}_{name}.png"))
        except Exception:
            pass

    # ── 1. 導航到首頁
    if "oiioii.ai" not in page.url:
        page.goto(OIIOII_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception:
        pass

    if not _is_logged_in(page):
        log.warning("  未偵測到登入狀態...")
        if not wait_for_login(page):
            return False

    _ss("home")

    # ── 2. 架設 Network 攔截器（在操作前）
    captured_http_urls: list[str] = []
    captured_blob_urls: list[str] = []

    def _on_response(response):
        url = response.url
        ct  = response.headers.get("content-type", "")
        if not (ct.startswith("video") or
                ".mp4" in url or
                "flow-content.google" in url or
                "storage.googleapis" in url):
            return
        if url.startswith("blob:"):
            if url not in captured_blob_urls:
                captured_blob_urls.append(url)
                log.info(f"  [NET] 攔截 blob 影片: {url[:60]}")
        else:
            if url not in captured_http_urls:
                captured_http_urls.append(url)
                log.info(f"  [NET] 攔截 HTTP 影片: {url[:80]}")

    page.on("response", _on_response)

    # ── 3. 點擊 "Free Canvas"（進入生影模式）
    # 優先用 selector，找不到再用座標
    free_canvas_clicked = False
    for sel in ['text="自由畫布"', 'text="Free Canvas"',
                'button:has-text("自由畫布")', 'button:has-text("Free Canvas")',
                '[class*="free" i]:has-text("Canvas")']:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0:
                btn.click(force=True)
                log.info("  ✓ 點擊 Free Canvas（selector）")
                free_canvas_clicked = True
                time.sleep(2)
                break
        except Exception:
            pass

    if not free_canvas_clicked:
        # 座標 fallback（viewport 1280×705 基準）
        log.info("  使用座標點擊 Free Canvas (758, 325)")
        page.mouse.click(758, 325)
        time.sleep(2)

    _ss("free_canvas")

    # ── 4. 選擇模型（Seedance 2.0 Pro）
    # 點擊 model selector（bars icon）
    log.info("  設定模型: Seedance 2.0 Pro")
    try:
        # 優先 selector
        model_sel = page.locator('[class*="model" i], [aria-label*="model" i]').first
        if model_sel.count() > 0:
            model_sel.click(force=True)
            time.sleep(1)
        else:
            page.mouse.click(165, 670)
            time.sleep(1)

        # 點 Video tab
        for sel in ['text="Video"', 'button:has-text("Video")', '[role="tab"]:has-text("Video")']:
            try:
                tab = page.locator(sel).first
                if tab.count() > 0:
                    tab.click(force=True)
                    time.sleep(0.8)
                    break
            except Exception:
                pass
        else:
            page.mouse.click(275, 430)
            time.sleep(0.8)

        # 選 Seedance 2.0 pro
        for sel in ['text="Seedance 2.0 pro"', 'text="Seedance 2.0 Pro"',
                    '[class*="model-item" i]:has-text("Seedance")']:
            try:
                item = page.locator(sel).first
                if item.count() > 0:
                    item.click(force=True)
                    log.info("  ✓ 選擇 Seedance 2.0 Pro（selector）")
                    time.sleep(0.8)
                    break
            except Exception:
                pass
        else:
            page.mouse.click(216, 530)
            time.sleep(0.8)

        # 關掉 Smart Model toggle（截圖確認後點座標，再截圖驗證 OFF 灰色狀態）
        _ss("before_smart_toggle")
        page.mouse.click(313, 400)
        time.sleep(0.5)
        _ss("after_smart_toggle")
        log.info("  ✓ 智能模型 toggle 已點擊 (313, 400)，截圖已存供驗證（確認呈灰色 OFF）")

    except Exception as e:
        log.warning(f"  模型選擇部分失敗 ({e})，繼續...")

    _ss("model_selected")

    # ── 5. 設定時長（6s）和解析度（720p）
    try:
        # 點齒輪（settings）
        for sel in ['[aria-label*="setting" i]', '[class*="setting" i]',
                    'button[title*="setting" i]']:
            try:
                gear = page.locator(sel).first
                if gear.count() > 0:
                    gear.click(force=True)
                    time.sleep(0.8)
                    break
            except Exception:
                pass
        else:
            page.mouse.click(315, 670)
            time.sleep(0.8)

        # 時長設定（點 + 按鈕到 6s，預設 10s，所以要點 - 幾次）
        # 或直接找輸入框
        duration_set = False
        for sel in ['input[type="number"]', '[class*="duration" i] input']:
            try:
                inp = page.locator(sel).first
                if inp.count() > 0:
                    inp.triple_click()
                    inp.type("6")
                    duration_set = True
                    log.info("  ✓ 設定時長 6s（input）")
                    break
            except Exception:
                pass

        if not duration_set:
            # 座標：點 - 按鈕 4 次（10s→6s）
            for _ in range(4):
                page.mouse.click(570, 555)  # - 按鈕
                time.sleep(0.3)
            log.info("  ✓ 設定時長 6s（座標）")

        # 解析度選 720p
        for sel in ['text="720p"', 'button:has-text("720p")']:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0:
                    btn.click(force=True)
                    log.info("  ✓ 設定 720p")
                    time.sleep(0.5)
                    break
            except Exception:
                pass

        # 關閉 settings panel（點畫布空白區域，不用 Escape 避免焦點丟失）
        page.mouse.click(800, 300)
        time.sleep(0.5)
        try:
            page.locator("textarea, [contenteditable='true']").first.click(force=True)
            time.sleep(0.3)
        except Exception:
            pass

    except Exception as e:
        log.warning(f"  settings 設定部分失敗 ({e})，繼續...")

    # ── 6. 輸入 prompt 並送出
    INPUT_SELS = [
        'textarea[placeholder*="prompt" i]',
        'textarea[placeholder*="describe" i]',
        'textarea[placeholder*="輸入" i]',
        '[contenteditable="true"][class*="input" i]',
        '[contenteditable="true"]',
        'textarea',
    ]

    prompt_box = None
    for sel in INPUT_SELS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.wait_for(state="visible", timeout=3000)
                if loc.is_visible():
                    prompt_box = loc
                    log.info(f"  ✓ 找到輸入框 [{sel[:50]}]")
                    break
        except Exception:
            continue

    if prompt_box:
        try:
            # 先用 JS focus 讓輸入框獲焦（繞過 _overlay_nimar_1 header overlay）
            try:
                page.evaluate("el => { el.focus(); el.scrollIntoView({block:'center'}); }",
                               prompt_box.element_handle())
                time.sleep(0.3)
            except Exception:
                pass
            # force=True 繞過 Playwright 的 actionability check（overlay 攔截問題）
            prompt_box.click(force=True)
            time.sleep(0.5)
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            # 逐字輸入（不用 fill，避免 paste 觸發 auto-submit）
            page.keyboard.type(prompt)
            log.info("  ✓ 已填入 prompt")
            time.sleep(1)
            _ss("prompt_filled")

            # 送出
            send_clicked = False
            for sel in ['button[type="submit"]', 'button:has-text("Send")',
                        'button:has-text("Generate")', 'button:has-text("生成")',
                        '[aria-label*="send" i]', '[class*="send" i]']:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0:
                        btn.click(force=True)
                        log.info(f"  ✓ 送出（{sel[:40]}）")
                        send_clicked = True
                        break
                except Exception:
                    pass

            if not send_clicked:
                # 座標 fallback
                page.mouse.click(487, 670)
                log.info("  送出（座標 487, 670）")

        except Exception as e:
            log.error(f"  填入/送出 prompt 失敗: {e}")
            _ss("prompt_failed")
            page.remove_listener("response", _on_response)
            return False
    else:
        # 純座標模式
        log.info("  找不到 selector，改用座標輸入")
        page.mouse.click(300, 605)
        time.sleep(0.5)
        page.keyboard.type(prompt)
        time.sleep(1)
        _ss("prompt_filled_coord")
        page.mouse.click(487, 670)
        log.info("  送出（座標）")

    _ss("generating")

    # ── 7. 等待生成完成（最多 5 分鐘）
    log.info("  等待 OiiOii Seedance 2.0 生成影片（最多 12 分鐘）...")
    found_elem = None

    for attempt in range(144):   # 144 × 5s = 12 分鐘
        time.sleep(5)

        if captured_http_urls:
            found_elem = "network_http"
            log.info(f"  ✓ Network 攔截到 HTTP 影片 URL（{(attempt + 1) * 5}s）")
            break

        if captured_blob_urls:
            found_elem = "network_blob"
            log.info(f"  ✓ Network 攔截到 blob 影片（{(attempt + 1) * 5}s）")
            break

        # 找 video 元素
        video_el = page.locator("video[src]")
        if video_el.count() > 0:
            src = video_el.first.get_attribute("src") or ""
            if src and not src.startswith("blob:"):
                captured_http_urls.append(src)
                found_elem = "video_src_http"
                break
            elif src and src.startswith("blob:"):
                if src not in captured_blob_urls:
                    captured_blob_urls.append(src)
                found_elem = "video_src_blob"
                break

        # 找下載按鈕
        dl_btn = page.locator(
            'a[download], button:has-text("Download"), button:has-text("下載"), '
            '[aria-label*="download" i], [class*="download" i] button'
        )
        if dl_btn.count() > 0:
            found_elem = "download_btn"
            log.info(f"  ✓ 找到下載按鈕（{(attempt + 1) * 5}s）")
            break

        if attempt % 6 == 5:
            log.info(f"  OiiOii 生成中... {(attempt + 1) * 5}s / 720s")
            _ss(f"wait_{attempt + 1}")

    try:
        page.remove_listener("response", _on_response)
    except Exception:
        pass

    if not found_elem:
        log.error("  ✗ OiiOii 生成逾時（12 分鐘）")
        _ss("timeout")
        return False

    _ss("generated")
    time.sleep(2)

    # ── 8. 下載影片（同 kling_browser 五策略）
    success = False

    if not success and found_elem == "download_btn":
        try:
            dl_loc = page.locator(
                'a[download], button:has-text("Download"), button:has-text("下載"), '
                '[aria-label*="download" i]'
            ).first
            if dl_loc.count() > 0:
                with page.expect_download(timeout=60000) as dl_info:
                    dl_loc.click(force=True)
                dl_info.value.save_as(str(output_path))
                log.info("  ✓ 策略A：Playwright Download")
                success = True
        except Exception as e:
            log.warning(f"  策略A 失敗: {e}")

    if not success and captured_http_urls:
        for url in reversed(captured_http_urls):
            if _download_http(url, output_path):
                log.info("  ✓ 策略B：HTTP URL")
                success = True
                break

    if not success:
        try:
            http_url = page.evaluate("""
                () => {
                    const v = document.querySelector('video[src]');
                    if (v && v.src && !v.src.startsWith('blob:')) return v.src;
                    for (const a of document.querySelectorAll('a[href*=".mp4"]'))
                        if (!a.href.startsWith('blob:')) return a.href;
                    return null;
                }
            """)
            if http_url and _download_http(http_url, output_path):
                log.info("  ✓ 策略C：DOM HTTP")
                success = True
        except Exception:
            pass

    if not success and captured_blob_urls:
        for blob_url in reversed(captured_blob_urls):
            if _download_blob(blob_url, output_path, page):
                log.info("  ✓ 策略D：blob JS-fetch")
                success = True
                break

    if not success:
        try:
            blob_url = page.evaluate("""
                () => {
                    const v = document.querySelector('video[src]');
                    if (v && v.src && v.src.startsWith('blob:')) return v.src;
                    return null;
                }
            """)
            if blob_url and _download_blob(blob_url, output_path, page):
                log.info("  ✓ 策略E：DOM blob")
                success = True
        except Exception:
            pass

    if success and output_path.exists() and output_path.stat().st_size > 200_000:
        log.info(f"  ✓ OiiOii 生影成功: {output_path.name} "
                 f"({output_path.stat().st_size // 1024} KB)")
        return True

    log.error("  ✗ OiiOii 生影失敗（所有下載策略均失敗）")
    _ss("download_failed")
    return False


# ── Entry point ──────────────────────────────────────────────────

def run(prompt: str, output_path: Path, login_only: bool = False) -> bool:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx  = get_context(pw, headless=False)
        page = ctx.new_page()

        log.info(f"開啟 OiiOii: {OIIOII_URL}")
        page.goto(OIIOII_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        try:
            page.keyboard.press("Escape")
            time.sleep(0.5)
        except Exception:
            pass

        if not _is_logged_in(page):
            if not wait_for_login(page):
                ctx.close()
                return False

        log.info("  ✓ OiiOii 登入狀態確認")

        if login_only:
            log.info("  --login-only 完成！OiiOii session 已儲存。")
            ctx.close()
            return True

        success = generate(prompt, output_path, page)
        ctx.close()
        return success


# ── CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OiiOii 瀏覽器生影")
    parser.add_argument("--prompt",     type=str, default="", help="影片描述提示詞")
    parser.add_argument("--output",     type=str, default="", help="輸出 MP4 路徑")
    parser.add_argument("--login-only", action="store_true",  help="只做登入，儲存 session")
    args = parser.parse_args()

    if args.login_only:
        run("", Path(""), login_only=True)
    elif args.prompt and args.output:
        ok = run(args.prompt, Path(args.output))
        sys.exit(0 if ok else 1)
    else:
        print("用法：python oiioii_browser.py --prompt '...' --output 'xxx.mp4'")
        print("      python oiioii_browser.py --login-only")
        sys.exit(1)
