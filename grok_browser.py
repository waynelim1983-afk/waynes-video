"""
grok_browser.py — 用 Playwright 操作 grok.com 生成影片（Grok 備援）

  - 免費 tier：每天 10 支影片（對備援需求綽綽有餘）
  - 規格：9:16 垂直，720p，最長 10 秒
  - 登入狀態存在獨立的 Chrome profile（不影響 YouTube / Google Flow）

首次執行前需登入：
  python grok_browser.py --login-only

正常生影：
  python grok_browser.py --prompt "..." --output "C:\\YT\\amazon\\output\\clips\\xxx.mp4"
"""

import sys
import re
import time
import base64
import argparse
import logging
import urllib.request
from pathlib import Path

BASE_DIR       = Path(r"C:\projects\YT\amazon")
LOG_FILE       = BASE_DIR / "logs" / "daily.log"
CHROME_PROFILE = BASE_DIR / "config" / "chrome_profile_grok"

# Grok 文字轉影片入口：grok.com/imagine
# 底部工具列有 圖片/影片/480p/720p/6s/10s/9:16 選項
# 免費 tier：480p、6s、9:16
GROK_URL = "https://grok.com/imagine"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GROK] %(message)s",
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
        viewport={"width": 1280, "height": 900},
        ignore_default_args=["--enable-automation"],
    )


# ── 登入確認 ────────────────────────────────────────────────────

def _is_logged_in(page) -> bool:
    try:
        url = page.url
        if "accounts.google.com" in url or "x.com/i/flow" in url:
            return False
        checks = [
            page.locator("textarea").count(),
            page.locator('[contenteditable="true"]').count(),
            page.locator('[data-testid*="Avatar"]').count(),
            page.locator('[aria-label*="account" i]').count(),
            page.locator('[aria-label*="profile" i]').count(),
            # grok.com 特有：側邊欄帳號區
            page.locator('nav a[href*="/profile"]').count(),
            page.locator('div[data-testid="UserCell"]').count(),
        ]
        return any(c > 0 for c in checks)
    except Exception:
        return False


def wait_for_login(page, timeout_s: int = 300) -> bool:
    log.info("=" * 50)
    log.info("請在瀏覽器視窗中登入 X (Twitter) / Google 帳號")
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


# ── 影片下載工具 ────────────────────────────────────────────────

def _download_http(url: str, output_path: Path) -> bool:
    """從 HTTP/HTTPS URL 下載影片。"""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            output_path.write_bytes(resp.read())
        size = output_path.stat().st_size
        if size < 100_000:
            log.warning(f"  下載檔案過小 ({size} bytes)，可能無效")
            return False
        log.info(f"  ✓ HTTP 下載完成 ({size // 1024} KB) → {output_path.name}")
        return True
    except Exception as e:
        log.error(f"  HTTP 下載失敗: {e}")
        return False


def _download_blob(blob_url: str, output_path: Path, page) -> bool:
    """透過 JS fetch() 讀取 blob URL 並以 base64 回傳給 Python。"""
    try:
        log.info(f"  嘗試 blob URL 下載: {blob_url[:60]}...")
        b64: str = page.evaluate(
            """async (url) => {
                const resp = await fetch(url);
                const buf  = await resp.arrayBuffer();
                const bytes = new Uint8Array(buf);
                let binary = '';
                const chunk = 8192;
                for (let i = 0; i < bytes.length; i += chunk) {
                    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
                }
                return btoa(binary);
            }""",
            blob_url,
        )
        if not b64:
            log.error("  blob fetch 回傳空值")
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(b64))
        size = output_path.stat().st_size
        if size < 100_000:
            log.warning(f"  blob 下載檔案過小 ({size} bytes)")
            return False
        log.info(f"  ✓ blob 下載完成 ({size // 1024} KB) → {output_path.name}")
        return True
    except Exception as e:
        log.error(f"  blob 下載失敗: {e}")
        return False


# ── 主要生成流程 ────────────────────────────────────────────────

def generate(prompt: str, output_path: Path, page) -> bool:
    """
    在已登入的 grok.com 頁面執行文字轉影片。
    Returns True on success.
    """
    log.info(f"Grok 生影 | prompt={prompt[:60]}...")

    # ── 1. 導航到 grok.com（主聊天，文字轉影片在這裡）
    if "grok.com" not in page.url:
        page.goto(GROK_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

    # ── 開頭先按 Escape，關掉任何殘留的 modal / dialog
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception:
        pass

    if not _is_logged_in(page):
        log.warning("  未偵測到登入，等待手動登入...")
        if not wait_for_login(page):
            return False

    # ── 截圖工具
    ss_dir = BASE_DIR / "logs" / "screenshots"
    ss_dir.mkdir(parents=True, exist_ok=True)

    def _ss(name: str):
        try:
            ts = time.strftime("%H%M%S")
            page.screenshot(path=str(ss_dir / f"grok_{ts}_{name}.png"))
        except Exception:
            pass

    _ss("loaded")

    # ── 2. 切換到「影片」模式（工具列的影片按鈕，不是 gallery 區塊）
    #   底部工具列：[Agent(Beta)] [圖片] [影片] [480p] [720p] [6s] [10s] [9:16]
    #   用 480p / 6s 等唯一文字找到工具列容器，再在裡面點「影片」
    try:
        # 找包含 "480p" 或 "6s" 的工具列容器（這些文字只在底部工具列出現）
        toolbar = page.locator(':has(button:has-text("480p")), :has(button:has-text("6s"))').last
        vid_btn = toolbar.locator('button:has-text("影片"), button:has-text("Video")')
        if vid_btn.count() > 0:
            vid_btn.first.click(force=True)
            time.sleep(0.8)
            log.info("  ✓ 切換到影片模式（工具列）")
        else:
            # fallback：直接找最後一個「影片」按鈕（避開 gallery 區）
            all_vid = page.locator('button:has-text("影片")')
            count = all_vid.count()
            if count > 0:
                all_vid.nth(count - 1).click(force=True)
                time.sleep(0.8)
                # 如果彈出上傳 modal 就關掉
                if page.locator('[role="dialog"], [aria-modal="true"]').count() > 0:
                    page.keyboard.press("Escape")
                    log.info("  影片按鈕觸發上傳 modal，已關閉")
                else:
                    log.info("  ✓ 切換到影片模式（fallback）")
    except Exception as e:
        log.warning(f"  切換影片模式失敗（{e}），繼續...")

    # ── 3. 設定免費參數：480p + 6s + 9:16
    #   免費 tier 只能用 480p 和 6s，720p/10s 是付費
    for param, candidates in [
        ("480p",  ["480p"]),
        ("6s",    ["6s"]),
        ("9:16",  ["9:16"]),
    ]:
        try:
            btn = page.locator(
                f'button:has-text("{candidates[0]}"), '
                f'[aria-label="{candidates[0]}"], '
                f'[title="{candidates[0]}"]'
            ).first
            if btn.count() > 0:
                btn.click(force=True)
                log.info(f"  ✓ 設定參數: {param}")
                time.sleep(0.4)
        except Exception:
            pass

    # ── 4. 找輸入框
    #   grok.com/imagine 底部輸入框 placeholder 是「輸入以想像」
    INPUT_SELS = [
        'input[placeholder*="想像" i]',
        'textarea[placeholder*="想像" i]',
        'div[contenteditable="true"][aria-label*="想像" i]',
        'input[placeholder*="imagine" i]',
        'textarea[placeholder*="imagine" i]',
        'textarea[placeholder*="prompt" i]',
        'div[contenteditable="true"][role="textbox"]',
        'div[contenteditable="true"]',
        'textarea',
        'input[type="text"]',
    ]

    prompt_box = None
    for sel in INPUT_SELS:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=3000)
            if loc.is_visible():
                prompt_box = loc
                log.info(f"  ✓ 找到輸入框 [{sel[:60]}]")
                break
        except Exception:
            continue

    if prompt_box is None:
        log.error("  找不到輸入框（所有 selector 均失敗）")
        _ss("no_input_box")
        return False

    # ── 5. 填入 prompt
    try:
        prompt_box.click()
        time.sleep(0.5)
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.keyboard.type(prompt)
        log.info(f"  ✓ 已填入 prompt")
        time.sleep(1)
    except Exception as e:
        log.error(f"  填入 prompt 失敗: {e}")
        _ss("prompt_fill_failed")
        return False

    _ss("prompt_filled")

    # ── 6. ★ 在按送出之前，先架好 Network 攔截器 ★
    #        早掛 → 才能捕捉到 Grok 回傳影片時的真實 HTTP URL
    captured_http_urls: list[str] = []   # 非 blob 的 .mp4 URL
    captured_blob_urls: list[str] = []   # blob: URL（備用）

    def _on_response(response):
        url = response.url
        ct  = response.headers.get("content-type", "")
        is_video = ".mp4" in url or "video" in ct
        if not is_video:
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

    # ── 7. 送出（Enter 最可靠；按鈕作為備援）
    #   Grok 聊天介面一般 Enter = 送出，Shift+Enter = 換行
    try:
        # 先試圖找送出按鈕（箭頭 ↑ 按鈕，aria-label 通常是 "Send"）
        send_sel = (
            'button[aria-label*="send" i], '
            'button[aria-label*="送出" i], '
            'button[aria-label*="Submit" i], '
            'button[type="submit"]:not([disabled]), '
            'button:has-text("Generate"), '
            'button:has-text("生成")'
        )
        send_btn = page.locator(send_sel).first
        if send_btn.count() > 0:
            send_btn.click(force=True)
            log.info("  ✓ 已點擊送出按鈕")
        else:
            raise Exception("找不到送出按鈕")
    except Exception as e:
        log.info(f"  ({e})，改用 Enter 送出")
        page.keyboard.press("Enter")

    _ss("generating")

    # ── 8. 等待影片生成完成（最多 3 分鐘）
    log.info("  等待 Grok 生成影片（最多 3 分鐘）...")
    found_elem = None

    for attempt in range(36):   # 36 × 5s = 3 分鐘
        time.sleep(5)

        # 優先：已從 network 攔截到 HTTP URL
        if captured_http_urls:
            found_elem = "network_http"
            log.info(f"  ✓ Network 攔截到 HTTP 影片 URL ({attempt + 1})")
            break

        # 方法 A: <video src> 非 blob
        video_el = page.locator("video[src]")
        if video_el.count() > 0:
            src = video_el.first.get_attribute("src") or ""
            if src and not src.startswith("blob:"):
                captured_http_urls.append(src)
                found_elem = "video_src_http"
                log.info(f"  ✓ <video src> (非 blob) ({attempt + 1})")
                break
            elif src and src.startswith("blob:"):
                if src not in captured_blob_urls:
                    captured_blob_urls.append(src)
                found_elem = "video_src_blob"
                log.info(f"  ✓ <video src> (blob) ({attempt + 1})")
                break

        # 方法 B: <source type="video/...">
        source_el = page.locator('source[type*="video"]')
        if source_el.count() > 0:
            src = source_el.first.get_attribute("src") or ""
            if src:
                if src.startswith("blob:"):
                    captured_blob_urls.append(src)
                    found_elem = "source_blob"
                else:
                    captured_http_urls.append(src)
                    found_elem = "source_http"
                log.info(f"  ✓ <source> 找到影片 ({attempt + 1})")
                break

        # 方法 C: 下載按鈕
        dl_btn = page.locator(
            'a[download], '
            'button:has-text("Download"), '
            'button:has-text("下載"), '
            '[aria-label*="download" i], '
            '[aria-label*="下載" i]'
        )
        if dl_btn.count() > 0:
            found_elem = "download_btn"
            log.info(f"  ✓ 找到下載按鈕 ({attempt + 1})")
            break

        if attempt % 6 == 5:
            log.info(f"  Grok 生成中... {(attempt + 1) * 5}s / 180s")
            _ss(f"wait_{attempt + 1}")

    # 移除監聽器
    try:
        page.remove_listener("response", _on_response)
    except Exception:
        pass

    if not found_elem:
        log.error("  ✗ Grok 生成逾時（3 分鐘）")
        _ss("timeout")
        return False

    _ss("generated")
    time.sleep(2)

    # ── 8. 依策略下載影片
    success = False

    # 策略 A：Playwright expect_download（點下載按鈕）
    if not success and found_elem == "download_btn":
        try:
            dl_loc = page.locator(
                'a[download], '
                'button:has-text("Download"), '
                'button:has-text("下載"), '
                '[aria-label*="download" i]'
            ).first
            with page.expect_download(timeout=60000) as dl_info:
                dl_loc.click(force=True)
            dl_info.value.save_as(str(output_path))
            log.info("  ✓ 策略A：Playwright Download 完成")
            success = True
        except Exception as e:
            log.warning(f"  策略A 失敗: {e}")

    # 策略 B：直接 HTTP 下載（已攔截或從 DOM 取得的 HTTPS URL）
    if not success and captured_http_urls:
        for url in reversed(captured_http_urls):   # 最新的先試
            if _download_http(url, output_path):
                log.info("  ✓ 策略B：HTTP URL 下載完成")
                success = True
                break

    # 策略 C：從 DOM 掃所有 <a href>.mp4 / <video src> (非 blob)
    if not success:
        try:
            http_url = page.evaluate("""
                () => {
                    const v = document.querySelector('video[src]');
                    if (v && v.src && !v.src.startsWith('blob:')) return v.src;
                    const s = document.querySelector('video source[src]');
                    if (s && s.src && !s.src.startsWith('blob:')) return s.src;
                    for (const a of document.querySelectorAll('a[href*=".mp4"], a[href*="video"]')) {
                        if (a.href && !a.href.startsWith('blob:')) return a.href;
                    }
                    return null;
                }
            """)
            if http_url:
                log.info(f"  策略C：DOM 取得 HTTP URL → {http_url[:80]}")
                if _download_http(http_url, output_path):
                    log.info("  ✓ 策略C：HTTP URL 下載完成")
                    success = True
        except Exception as e:
            log.warning(f"  策略C 失敗: {e}")

    # 策略 D：blob URL → JS fetch() → base64 → bytes
    if not success and captured_blob_urls:
        for blob_url in reversed(captured_blob_urls):
            if _download_blob(blob_url, output_path, page):
                log.info("  ✓ 策略D：blob URL JS-fetch 下載完成")
                success = True
                break

    # 策略 E：從 DOM 找 blob URL 再用 JS fetch
    if not success:
        try:
            blob_url = page.evaluate("""
                () => {
                    const v = document.querySelector('video[src]');
                    if (v && v.src && v.src.startsWith('blob:')) return v.src;
                    const s = document.querySelector('video source[src]');
                    if (s && s.src && s.src.startsWith('blob:')) return s.src;
                    return null;
                }
            """)
            if blob_url:
                log.info(f"  策略E：DOM blob URL → JS fetch")
                if _download_blob(blob_url, output_path, page):
                    log.info("  ✓ 策略E：blob JS-fetch 完成")
                    success = True
        except Exception as e:
            log.warning(f"  策略E 失敗: {e}")

    if success and output_path.exists() and output_path.stat().st_size > 200_000:
        log.info(f"  ✓ Grok 生影成功: {output_path.name} "
                 f"({output_path.stat().st_size // 1024} KB)")
        return True

    log.error("  ✗ Grok 生影失敗（所有下載策略均失敗）")
    _ss("download_failed")
    return False


# ── Entry point ─────────────────────────────────────────────────

def run(prompt: str, output_path: Path, login_only: bool = False) -> bool:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx  = get_context(pw, headless=False)
        page = ctx.new_page()

        log.info(f"開啟 Grok: {GROK_URL}")
        page.goto(GROK_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # 關掉開場 modal（如新功能介紹彈窗）
        try:
            page.keyboard.press("Escape")
            time.sleep(0.5)
        except Exception:
            pass

        if not _is_logged_in(page):
            if not wait_for_login(page):
                ctx.close()
                return False

        log.info("  ✓ Grok 登入狀態確認")

        if login_only:
            log.info("  --login-only 完成！Grok session 已儲存。")
            ctx.close()
            return True

        success = generate(prompt, output_path, page)
        ctx.close()
        return success


# ── CLI ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grok 瀏覽器生影")
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
        print("用法：python grok_browser.py --prompt '...' --output 'xxx.mp4'")
        print("      python grok_browser.py --login-only")
        sys.exit(1)
