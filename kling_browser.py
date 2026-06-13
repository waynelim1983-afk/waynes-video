"""
kling_browser.py — 用 Playwright 操作 kling.ai 生成影片（Kling AI 備援）

  - 免費 tier：依帳號，Standard 5s 每支消耗 10 credits
  - 規格：9:16 垂直，720p，5 秒（免費標準品質）
  - 影片有 Kling 浮水印（免費限制）
  - 登入狀態存在獨立的 Chrome profile
  - URL: https://kling.ai/app/video/new（Kling 3.0，2026）

首次執行前需登入：
  python kling_browser.py --login-only

正常生影：
  python kling_browser.py --prompt "..." --output "C:\\YT\\amazon\\output\\clips\\xxx.mp4"
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
CHROME_PROFILE = BASE_DIR / "config" / "chrome_profile_kling"

KLING_URL = "https://kling.ai/app/video/new"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [KLING] %(message)s",
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
        viewport={"width": 1568, "height": 708},
        ignore_default_args=["--enable-automation"],
    )


# ── 登入確認 ────────────────────────────────────────────────────

def _is_logged_in(page) -> bool:
    """
    只在看到明確的「已登入後才有」的 UI 元素時才回傳 True。
    判斷標準（截圖確認）：
      - 左下角有 "Upgrade subscription" 按鈕（登入後才有）
      - 且頁面上沒有 email/password 輸入框（確保登入流程已完成）
    """
    try:
        url = page.url
        if "login" in url or "signin" in url or "auth" in url:
            return False

        # 如果還看得到 email/password 輸入框 → 還在登入流程中
        login_form = page.locator(
            'input[type="email"], input[type="password"], '
            'button:has-text("Sign in"), button:has-text("Log in"), '
            'button:has-text("登入"), button:has-text("繼續"), '
            '[class*="login" i] input'
        ).count()
        if login_form > 0:
            return False

        # 登入後才有的元素（廣泛偵測）
        strong = [
            page.locator('button:has-text("Upgrade")').count(),
            page.locator(':has-text("Upgrade subscription")').count(),
            page.locator('[class*="user-name" i]').count(),
            page.locator('[class*="username" i]').count(),
            page.locator('[class*="coin" i]').count(),
            page.locator('[class*="credit" i]').count(),
        ]
        if any(c > 0 for c in strong):
            return True

        # 最後防線：URL 在 /app/ 且沒有登入表單 → 視為已登入
        if "/app/" in url and login_form == 0:
            return True

        return False

    except Exception:
        return False


def wait_for_login(page, timeout_s: int = 300) -> bool:
    log.info("=" * 50)
    log.info("請在瀏覽器視窗中登入 Kling AI 帳號")
    log.info("支援 Google / Email 登入")
    log.info("登入後程式會自動偵測並繼續...")
    log.info("（等待 25 秒後開始偵測，請先完成帳號密碼輸入）")
    log.info("=" * 50)

    # 至少等 25 秒，讓使用者有時間輸入帳號密碼
    time.sleep(25)
    log.info("  開始偵測登入狀態...")

    for i in range(timeout_s // 3):
        time.sleep(3)
        if _is_logged_in(page):
            log.info(f"  ✓ 偵測到登入成功（等待 {25 + (i + 1) * 3}s）")
            return True
        if i % 10 == 9:
            log.info(f"  等待中... ({25 + (i + 1) * 3}s / {timeout_s + 25}s)")
    log.error("登入逾時")
    return False


# ── 影片下載工具 ────────────────────────────────────────────────

def _download_http(url: str, output_path: Path) -> bool:
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
    在已登入的 klingai.com 頁面執行文字轉影片。
    Returns True on success.
    """
    prompt = validate_prompt("kling", prompt)
    log.info(f"Kling 生影 | prompt={prompt[:60]}...")

    # 截圖工具
    ss_dir = BASE_DIR / "logs" / "screenshots"
    ss_dir.mkdir(parents=True, exist_ok=True)

    def _ss(name: str):
        try:
            ts = time.strftime("%H%M%S")
            page.screenshot(path=str(ss_dir / f"kling_{ts}_{name}.png"))
        except Exception:
            pass

    # ── 1. 導航到生影頁面
    if "kling.ai" not in page.url or "video/new" not in page.url:
        page.goto(KLING_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

    # 關掉任何殘留的 modal
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception:
        pass

    if not _is_logged_in(page):
        log.warning("  未偵測到登入狀態，等待手動登入...")
        if not wait_for_login(page):
            return False

    _ss("loaded")

    # ── 2. 找提示詞輸入框
    INPUT_SELS = [
        'textarea[placeholder*="prompt" i]',
        'textarea[placeholder*="Prompt" i]',
        'textarea[placeholder*="描述" i]',
        'textarea[placeholder*="describe" i]',
        'div[contenteditable="true"][class*="input" i]',
        'div[contenteditable="true"][class*="editor" i]',
        'div[contenteditable="true"]',
        'textarea',
    ]

    prompt_box = None
    for sel in INPUT_SELS:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=4000)
            if loc.is_visible():
                prompt_box = loc
                log.info(f"  ✓ 找到輸入框 [{sel[:60]}]")
                break
        except Exception:
            continue

    if prompt_box is None:
        log.error("  找不到提示詞輸入框（所有 selector 均失敗）")
        _ss("no_input_box")
        return False

    # ── 3. 設定參數（Fast mode / 5s / 9:16）
    # Fast mode：點左下參數列 (145,715) 開設定面板
    try:
        page.mouse.click(145, 715)
        time.sleep(0.8)
        fast_set = False
        for text in ["Fast", "快速", "Fast mode"]:
            try:
                btn = page.locator(
                    f'button:has-text("{text}"), '
                    f'[role="radio"]:has-text("{text}"), '
                    f'[aria-label*="{text}"], '
                    f'label:has-text("{text}")'
                ).first
                if btn.count() > 0:
                    btn.click(force=True)
                    log.info(f"  ✓ 設定 Fast mode: {text}")
                    time.sleep(0.4)
                    fast_set = True
                    break
            except Exception:
                pass
        if not fast_set:
            log.info("  Fast mode 按鈕未找到，預設可能已對，繼續...")
    except Exception as e:
        log.warning(f"  Fast mode 設定失敗 ({e})，繼續...")

    for label, candidates in [
        ("5s",   ["5s", "5 秒"]),
        ("9:16", ["9:16"]),
    ]:
        for text in candidates:
            try:
                btn = page.locator(
                    f'button:has-text("{text}"), '
                    f'[role="radio"]:has-text("{text}"), '
                    f'[aria-label*="{text}"], '
                    f'[title*="{text}"], '
                    f'label:has-text("{text}")'
                ).first
                if btn.count() > 0:
                    btn.click(force=True)
                    log.info(f"  ✓ 設定 {label}: {text}")
                    time.sleep(0.4)
                    break
            except Exception:
                pass

    # ── 4. 填入 prompt
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

    # ── 5. 架設 Network 攔截器（在送出前）
    captured_http_urls: list[str] = []
    captured_blob_urls: list[str] = []

    def _on_response(response):
        url = response.url
        ct  = response.headers.get("content-type", "")
        is_video = ".mp4" in url or "video" in ct or "/clip/" in url
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

    # ── 6. 點擊生成按鈕
    GENERATE_SELS = (
        'button:has-text("Generate"), '
        'button:has-text("生成"), '
        'button:has-text("Create"), '
        'button:has-text("創建"), '
        'button[type="submit"]:not([disabled]), '
        '[class*="generate" i]:not([disabled]), '
        '[class*="submit" i] button:not([disabled])'
    )
    try:
        gen_btn = page.locator(GENERATE_SELS).first
        if gen_btn.count() == 0:
            raise Exception("找不到生成按鈕")
        gen_btn.click(force=True)
        log.info("  ✓ 已點擊生成按鈕")
    except Exception as e:
        log.error(f"  點擊生成按鈕失敗: {e}")
        _ss("no_generate_btn")
        page.remove_listener("response", _on_response)
        return False

    _ss("generating")

    # ── 7. 等待生成完成（最多 8 分鐘）
    #   Kling 生成通常 3–7 分鐘（高峰期更久）
    log.info("  等待 Kling AI 生成影片（最多 8 分鐘）...")
    found_elem = None

    for attempt in range(96):   # 96 × 5s = 8 分鐘
        time.sleep(5)

        # 優先：已從 network 攔截到 HTTP URL
        if captured_http_urls:
            found_elem = "network_http"
            log.info(f"  ✓ Network 攔截到 HTTP 影片 URL（{(attempt + 1) * 5}s）")
            break

        try:
            # 方法 A: <video src> 非 blob
            video_el = page.locator("video[src]")
            if video_el.count() > 0:
                src = video_el.first.get_attribute("src") or ""
                if src and not src.startswith("blob:"):
                    captured_http_urls.append(src)
                    found_elem = "video_src_http"
                    log.info(f"  ✓ <video src> (HTTP) ({(attempt + 1) * 5}s)")
                    break
                elif src and src.startswith("blob:"):
                    if src not in captured_blob_urls:
                        captured_blob_urls.append(src)
                    found_elem = "video_src_blob"
                    log.info(f"  ✓ <video src> (blob) ({(attempt + 1) * 5}s)")
                    break
        except Exception as e:
            log.warning(f"  等待中頁面異常 ({type(e).__name__})，重試...")
            time.sleep(3)
            continue

        try:
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
                    log.info(f"  ✓ <source> 找到影片 ({(attempt + 1) * 5}s)")
                    break

            # 方法 C: 下載按鈕出現
            dl_btn = page.locator(
                'a[download], '
                'button:has-text("Download"), '
                'button:has-text("下載"), '
                '[aria-label*="download" i], '
                '[aria-label*="下載" i], '
                '[class*="download" i] button'
            )
            if dl_btn.count() > 0:
                found_elem = "download_btn"
                log.info(f"  ✓ 找到下載按鈕 ({(attempt + 1) * 5}s)")
                break

            # 方法 D: 完成狀態指示
            done_el = page.locator(
                '[class*="complete" i]:visible, '
                '[class*="success" i]:visible, '
                '[class*="finished" i]:visible'
            )
            if done_el.count() > 0:
                found_elem = "status_complete"
                log.info(f"  ✓ 偵測到完成狀態 ({(attempt + 1) * 5}s)")
                break

            if attempt % 6 == 5:
                log.info(f"  Kling 生成中... {(attempt + 1) * 5}s / 480s")
                _ss(f"wait_{attempt + 1}")

        except Exception as e:
            log.warning(f"  等待中頁面異常 ({type(e).__name__})，重試...")
            time.sleep(3)
            continue

    try:
        page.remove_listener("response", _on_response)
    except Exception:
        pass

    if not found_elem:
        log.error("  ✗ Kling 生成逾時（8 分鐘）")
        _ss("timeout")
        return False

    _ss("generated")
    time.sleep(2)

    # ── 8. 依策略下載影片
    success = False

    # 策略 A：Playwright expect_download（點下載按鈕）
    if not success and found_elem in ("download_btn", "status_complete"):
        try:
            dl_loc = page.locator(
                'a[download], '
                'button:has-text("Download"), '
                'button:has-text("下載"), '
                '[aria-label*="download" i], '
                '[class*="download" i] button'
            ).first
            if dl_loc.count() > 0:
                with page.expect_download(timeout=60000) as dl_info:
                    dl_loc.click(force=True)
                dl_info.value.save_as(str(output_path))
                log.info("  ✓ 策略A：Playwright Download 完成")
                success = True
        except Exception as e:
            log.warning(f"  策略A 失敗: {e}")

    # 策略 B：直接 HTTP 下載
    if not success and captured_http_urls:
        for url in reversed(captured_http_urls):
            if _download_http(url, output_path):
                log.info("  ✓ 策略B：HTTP URL 下載完成")
                success = True
                break

    # 策略 C：從 DOM 掃 HTTP URL
    if not success:
        try:
            http_url = page.evaluate("""
                () => {
                    const v = document.querySelector('video[src]');
                    if (v && v.src && !v.src.startsWith('blob:')) return v.src;
                    const s = document.querySelector('video source[src]');
                    if (s && s.src && !s.src.startsWith('blob:')) return s.src;
                    for (const a of document.querySelectorAll('a[href*=".mp4"], a[href*="video"], a[href*="clip"]')) {
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

    # 策略 D：blob URL → JS fetch() → base64
    if not success and captured_blob_urls:
        for blob_url in reversed(captured_blob_urls):
            if _download_blob(blob_url, output_path, page):
                log.info("  ✓ 策略D：blob JS-fetch 下載完成")
                success = True
                break

    # 策略 E：DOM 找 blob URL
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
        log.info(f"  ✓ Kling 生影成功: {output_path.name} "
                 f"({output_path.stat().st_size // 1024} KB)")
        return True

    log.error("  ✗ Kling 生影失敗（所有下載策略均失敗）")
    _ss("download_failed")
    return False


# ── Entry point ─────────────────────────────────────────────────

def run(prompt: str, output_path: Path, login_only: bool = False) -> bool:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx  = get_context(pw, headless=False)
        page = ctx.new_page()

        log.info(f"開啟 Kling AI: {KLING_URL}")
        page.goto(KLING_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        try:
            page.keyboard.press("Escape")
            time.sleep(0.5)
        except Exception:
            pass

        if login_only:
            # --login-only 一定要等使用者手動完成登入，不走快速判斷
            if not wait_for_login(page):
                ctx.close()
                return False
        elif not _is_logged_in(page):
            # 生影模式：先快速判斷，沒登入再等
            if not wait_for_login(page):
                ctx.close()
                return False

        log.info("  ✓ Kling AI 登入狀態確認")

        if login_only:
            log.info("  --login-only 完成！Kling session 已儲存。")
            log.info("  3 秒後關閉瀏覽器...")
            time.sleep(3)
            ctx.close()
            return True

        success = generate(prompt, output_path, page)
        ctx.close()
        return success


# ── CLI ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kling AI 瀏覽器生影")
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
        print("用法：python kling_browser.py --prompt '...' --output 'xxx.mp4'")
        print("      python kling_browser.py --login-only")
        sys.exit(1)
