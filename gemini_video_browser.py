"""
gemini_video_browser.py — Gemini Web (gemini.google.com) 影片生成

用 Playwright 自動化 gemini.google.com 的「建立影片」功能（用 Omni 生成）。
使用現有 Chrome profile（已登入 Google），不需要額外 API key。

需要 Gemini Advanced / Gemini 訂閱方案（含影片生成功能）。

Usage:
  python gemini_video_browser.py --prompt "A cat playing with a red ball" --output out.mp4
  python gemini_video_browser.py --login-only   # 開啟瀏覽器讓你手動登入
"""

import os
import sys
import time
import logging
import argparse
import zipfile
import tempfile
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "logs" / "daily.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GEMINI-WEB] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w",
                 encoding="utf-8", errors="replace", closefd=False)
        ),
    ],
)
log = logging.getLogger(__name__)

GEMINI_URL = "https://gemini.google.com"
CHROME_PROFILE = BASE_DIR / "config" / "chrome_profile_gemini_web"

# ── Chrome context ────────────────────────────────────────────────────────────

def get_context(playwright, headless: bool = False):
    """Launch Playwright Chromium with a persistent profile."""
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)

    # Kill any existing Chrome to avoid profile lock (TargetClosedError)
    log.info("  Killing existing Chrome instances to release profile lock...")
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                   capture_output=True, text=True)
    time.sleep(2)

    # Try real Chrome binary first (better compatibility with gemini.google.com)
    chrome_bins = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
    ]
    chrome_bin = next((p for p in chrome_bins if Path(p).exists()), None)

    launch_args = dict(
        user_data_dir=str(CHROME_PROFILE),
        headless=headless,
        args=[
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
        ignore_default_args=["--enable-automation"],
    )

    if chrome_bin:
        launch_args["executable_path"] = chrome_bin
        log.info(f"  Using Chrome binary: {chrome_bin}")

    return playwright.chromium.launch_persistent_context(**launch_args)


def _is_logged_in(page) -> bool:
    """Check if the user is logged in to Gemini."""
    try:
        page.goto(GEMINI_URL, timeout=20000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        import time as _time; _time.sleep(3)
        # If redirected to accounts.google.com → not logged in
        if "accounts.google.com" in page.url:
            return False
        # Look for signs of logged-in state
        logged_in_signals = [
            'img[alt*="profile" i]',
            '[aria-label*="Google Account" i]',
            'button[aria-label*="profile" i]',
            '[data-testid*="user" i]',
        ]
        for sel in logged_in_signals:
            if page.locator(sel).count() > 0:
                return True
        # If still on gemini.google.com, assume logged in
        return "gemini.google.com" in page.url
    except Exception as e:
        log.warning(f"  Login check error: {e}")
        return False


def login_only() -> bool:
    """Open browser for manual login."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = get_context(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(GEMINI_URL)
        log.info("  Browser opened. Please log in to Google, then close the browser.")
        try:
            page.wait_for_event("close", timeout=300000)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass  # browser already closed by user — that's fine
    return True


# ── Navigate to video creation ────────────────────────────────────────────────

def _navigate_to_video_mode(page) -> bool:
    """
    Navigate to Gemini and activate video creation mode.

    Per Google support docs (2026):
      1. Go to gemini.google.com
      2. Click "Add Files" (+ button at bottom of input)
      3. Click "Create video" / "建立影片" from the popup menu
      4. Then enter prompt in the text box
    """
    log.info("  Navigating to Gemini...")
    page.goto(f"{GEMINI_URL}/app", timeout=30000)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    time.sleep(4)
    page.screenshot(path=str(BASE_DIR / "logs" / "gemini_after_load.png"))
    log.info(f"  URL: {page.url}")

    # ── Step 1: click the 上傳與工具 button near the input ──────────────────
    # Confirmed from DOM dump: button[aria-label="上傳與工具"]
    add_selectors = [
        'button[aria-label="上傳與工具"]',                  # CONFIRMED
        'button[aria-label*="上傳與工具" i]',
        'button[aria-label*="Upload and tools" i]',
        'button[aria-label*="Add files" i]',
        'button[aria-label*="新增檔案" i]',
        'button[aria-label*="新增" i]',
        'button[aria-label*="附加" i]',
        'button[aria-label*="attach" i]',
        '[data-testid*="add-file" i]',
    ]
    clicked_add = False
    for sel in add_selectors:
        loc = page.locator(sel)
        if loc.count() > 0 and loc.first.is_visible():
            loc.first.click()
            log.info(f"  ✓ Clicked Add Files [{sel}]")
            time.sleep(1.5)
            clicked_add = True
            break

    if not clicked_add:
        # JS fallback: find button near input area (contenteditable or textarea)
        result = page.evaluate("""
            () => {
                // Try contenteditable div first (Gemini uses this), then textarea
                const input = document.querySelector(
                    'div[contenteditable="true"], textarea, [role="textbox"]'
                );
                if (!input) return null;
                const area = input.closest('form') || input.closest('[class*="input"]') || input.parentElement?.parentElement;
                if (!area) return null;
                const btns = [...area.querySelectorAll('button, [role="button"]')];
                const kws = ['add', 'upload', 'attach', '上傳', '新增', '附加'];
                const target = btns.find(b => {
                    const lbl = (b.getAttribute('aria-label') || '').toLowerCase();
                    const txt = (b.textContent || '').trim();
                    return kws.some(k => lbl.includes(k) || txt.includes(k)) || txt === '+';
                });
                if (target) { target.click(); return target.getAttribute('aria-label') || target.textContent?.slice(0,30); }
                return null;
            }
        """)
        if result:
            log.info(f"  ✓ JS clicked Add Files: {result}")
            time.sleep(1.5)
            clicked_add = True

    page.screenshot(path=str(BASE_DIR / "logs" / "gemini_after_add_click.png"))

    # ── Step 2: click "Create video" / "建立影片" in the popup menu ──────────
    # Confirmed from DOM dump: button has role="menuitemcheckbox" and text="建立影片"
    video_menu_selectors = [
        'button[role="menuitemcheckbox"]:has-text("建立影片")',  # CONFIRMED from DOM dump
        'button[role="menuitemcheckbox"]:has-text("Create video")',
        ':text-is("建立影片")',
        ':text("建立影片")',
        ':text("Create video")',
        'button[aria-label*="建立影片" i]',
        'button[aria-label*="Create video" i]',
        '[role="menuitemcheckbox"]:has-text("影片")',
        '[role="menuitem"]:has-text("影片")',
        'li:has-text("建立影片")',
    ]
    for sel in video_menu_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click()
                log.info(f"  ✓ Clicked Create video [{sel}]")
                time.sleep(2)
                _dismiss_video_intro_modal(page)
                page.screenshot(path=str(BASE_DIR / "logs" / "gemini_video_mode.png"))
                return True
        except Exception:
            pass

    # JS fallback for menu — includes menuitemcheckbox (confirmed role)
    result = page.evaluate("""
        () => {
            const kws = ['建立影片', 'Create video'];
            const all = [...document.querySelectorAll(
                'button, [role="menuitemcheckbox"], [role="menuitem"], [role="option"], li'
            )];
            for (const kw of kws) {
                const el = all.find(e =>
                    (e.textContent || '').trim() === kw ||
                    (e.textContent || '').trim().startsWith(kw)
                );
                if (el && el.offsetParent !== null) {
                    el.click();
                    return (el.textContent || '').trim().slice(0, 40);
                }
            }
            return null;
        }
    """)
    if result:
        log.info(f"  ✓ JS clicked Create video: {result}")
        time.sleep(2)
        _dismiss_video_intro_modal(page)
        page.screenshot(path=str(BASE_DIR / "logs" / "gemini_video_mode.png"))
        return True

    log.warning("  Could not find Create video button — will try direct prompt")
    page.screenshot(path=str(BASE_DIR / "logs" / "gemini_video_mode_fail.png"))
    return False


def _dismiss_video_intro_modal(page) -> None:
    """
    Dismiss the 'Create video' intro modal if it appears.
    The modal has a '立即體驗' / 'Get started' button.
    If present, clicking it dismisses the overlay so the input becomes accessible.
    """
    modal_dismiss_selectors = [
        'button:has-text("立即體驗")',    # zh-TW "Get started"
        'button:has-text("Get started")',
        'button:has-text("Try it")',
        'button:has-text("Try now")',
        '[data-testid*="cta" i]',
    ]
    for sel in modal_dismiss_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible(timeout=2000):
                loc.first.click()
                log.info(f"  Dismissed intro modal [{sel}]")
                time.sleep(1)
                return
        except Exception:
            pass
    # Try Escape key as last resort
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception:
        pass


# ── Submit prompt and wait for video ─────────────────────────────────────────

def _submit_prompt(page, prompt: str) -> bool:
    """Type prompt and click generate."""
    # Find the text input — confirmed from DOM dump: contenteditable div with aria '請輸入 Gemini 提示詞'
    input_selectors = [
        'div[aria-label="請輸入 Gemini 提示詞"][contenteditable="true"]',  # CONFIRMED
        'div[aria-label*="提示詞"][contenteditable="true"]',
        'div[aria-label*="prompt" i][contenteditable="true"]',
        'div[contenteditable="true"]',
        'textarea[placeholder*="描述" i]',
        'textarea[placeholder*="prompt" i]',
        'textarea',
        '[role="textbox"]',
    ]
    input_el = None
    for sel in input_selectors:
        loc = page.locator(sel)
        try:
            if loc.count() > 0 and loc.first.is_visible():
                input_el = loc.first
                log.info(f"  Input found [{sel}]")
                break
        except Exception:
            pass

    if not input_el:
        log.error("  Cannot find text input")
        page.screenshot(path=str(BASE_DIR / "logs" / "gemini_no_input.png"))
        return False

    # Focus and type the prompt
    # Use click() + keyboard.type() for contenteditable divs (fill() may not work)
    try:
        input_el.click()
        time.sleep(0.5)
        # Clear existing content via Ctrl+A + Delete
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        time.sleep(0.2)
        # Type the prompt
        page.keyboard.type(prompt, delay=10)
        time.sleep(0.5)
        log.info(f"  Typed prompt: {prompt[:60]}...")
    except Exception as e:
        log.warning(f"  keyboard.type failed: {e}, trying fill()...")
        try:
            input_el.fill(prompt)
            time.sleep(0.5)
        except Exception as e2:
            log.error(f"  fill() also failed: {e2}")
            return False

    # Wait a moment for send button to appear
    time.sleep(1)
    page.screenshot(path=str(BASE_DIR / "logs" / "gemini_before_send.png"))

    # Find and click send/generate button — try several aria-labels
    generate_selectors = [
        'button[aria-label*="傳送" i]',         # 傳送 = Send in zh-TW Gemini
        'button[aria-label*="Send" i]',
        'button[aria-label*="生成影片" i]',
        'button[aria-label*="生成" i]',
        'button[aria-label*="Generate" i]',
        'button[aria-label*="提交" i]',
        'button:has-text("生成")',
        'button:has-text("Generate")',
    ]
    for sel in generate_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click()
                log.info(f"  Clicked send/generate [{sel}]")
                return True
        except Exception:
            pass

    # JS fallback: find send button by searching near input area
    result = page.evaluate("""
        () => {
            // Look for buttons near the input area that are not disabled
            const btns = [...document.querySelectorAll('button:not([disabled])')];
            // Filter to ones that look like send buttons (by aria-label or position)
            const sendKws = ['傳送', 'Send', '生成', 'Generate', 'submit', 'send'];
            for (const kw of sendKws) {
                const btn = btns.find(b =>
                    (b.getAttribute('aria-label') || '').toLowerCase().includes(kw.toLowerCase()) ||
                    (b.textContent || '').trim().toLowerCase().includes(kw.toLowerCase())
                );
                if (btn && btn.offsetParent !== null) {
                    btn.click();
                    return btn.getAttribute('aria-label') || btn.textContent?.trim() || 'clicked';
                }
            }
            // Last resort: find the last enabled button in the input toolbar
            const enabled = btns.filter(b => b.offsetParent !== null);
            if (enabled.length > 0) {
                const last = enabled[enabled.length - 1];
                last.click();
                return 'last-button: ' + (last.getAttribute('aria-label') || last.textContent?.trim() || '?');
            }
            return null;
        }
    """)
    if result:
        log.info(f"  JS send button: {result}")
        return True

    # Ultimate fallback: Enter key
    log.info("  Using Enter key to submit...")
    input_el.press("Enter")
    return True


def _wait_and_download(page, output_path: Path, max_wait: int = 300) -> bool:
    """
    Wait for Gemini to generate the video, then download it.
    Returns True if video was saved to output_path.
    """
    log.info(f"  Waiting for video generation (max {max_wait}s)...")
    deadline = time.time() + max_wait
    video_url = None

    # Strategy A: intercept network response for video file
    videos_found = []

    def handle_response(response):
        url = response.url
        ct  = response.headers.get("content-type", "")
        if (url.endswith(".mp4") or "video/mp4" in ct or
                ("storage.googleapis.com" in url and "mp4" in url.lower()) or
                ("video" in url.lower() and not url.endswith(".js"))):
            videos_found.append(url)
            log.info(f"  ✓ Video URL intercepted: {url[:80]}")

    page.on("response", handle_response)

    while time.time() < deadline:
        time.sleep(3)
        elapsed = int(time.time() - (deadline - max_wait))

        # Check intercepted URLs
        if videos_found:
            video_url = videos_found[-1]
            break

        # Check DOM for video/download elements
        video_el = page.locator(
            'video[src], '
            'video source[src], '
            'a[href*=".mp4"], '
            'a[download]'
        )
        if video_el.count() > 0:
            src = (
                video_el.first.get_attribute("src") or
                video_el.first.get_attribute("href") or ""
            )
            if src and ("mp4" in src.lower() or src.startswith("http") or src.startswith("blob")):
                video_url = src
                log.info(f"  ✓ Video element found: {src[:80]}")
                break

        # Check for error messages
        err_sels = [':text("無法生成")', ':text("發生錯誤")', ':text("error" )', ':text("failed")']
        for sel in err_sels:
            if page.locator(sel).count() > 0:
                log.error(f"  Error detected on page [{sel}]")
                page.screenshot(path=str(BASE_DIR / "logs" / "gemini_gen_error.png"))
                return False

        if elapsed % 30 == 0 and elapsed > 0:
            log.info(f"  Still waiting... {elapsed}s elapsed")
            page.screenshot(path=str(BASE_DIR / "logs" / f"gemini_wait_{elapsed}s.png"))

    page.remove_listener("response", handle_response)

    if not video_url:
        log.error("  Timed out waiting for video")
        page.screenshot(path=str(BASE_DIR / "logs" / "gemini_timeout.png"))
        return False

    # Download the video
    log.info(f"  Downloading from: {video_url[:80]}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if video_url.startswith("blob:"):
        # Blob URL: extract via JS
        log.info("  Blob URL detected — extracting via JS fetch...")
        data_b64 = page.evaluate("""
            async (blobUrl) => {
                const r = await fetch(blobUrl);
                const buf = await r.arrayBuffer();
                const bytes = new Uint8Array(buf);
                let bin = '';
                for (let i = 0; i < bytes.byteLength; i++) bin += String.fromCharCode(bytes[i]);
                return btoa(bin);
            }
        """, video_url)
        if data_b64:
            import base64
            output_path.write_bytes(base64.b64decode(data_b64))
            log.info(f"  ✓ Saved blob video to {output_path} ({output_path.stat().st_size // 1024} KB)")
            return True
        else:
            log.error("  Blob extraction failed")
            return False
    else:
        # Regular URL: use page.request
        try:
            resp = page.request.get(video_url)
            if resp.ok:
                output_path.write_bytes(resp.body())
                log.info(f"  Saved to {output_path} ({output_path.stat().st_size // 1024} KB)")
                return output_path.stat().st_size > 100_000
            else:
                log.error(f"  HTTP {resp.status} downloading video")
                return False
        except Exception as e:
            log.error(f"  Download failed: {e}")
            return False


# ── Main generate function ────────────────────────────────────────────────────

def generate(prompt: str, output_path: Path, max_wait: int = 300) -> bool:
    """
    Generate a video on gemini.google.com using the Omni model.
    Returns True if video was successfully saved to output_path.
    """
    from playwright.sync_api import sync_playwright

    log.info(f"Gemini Web video generation: {prompt[:60]}...")

    with sync_playwright() as p:
        ctx = get_context(p, headless=False)  # headless=False for Google auth
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        try:
            # Check login
            if not _is_logged_in(page):
                log.error("  Not logged in to Gemini. Run: python gemini_video_browser.py --login-only")
                return False

            log.info("  Logged in to Gemini")

            # Navigate to video mode
            if not _navigate_to_video_mode(page):
                log.warning("  Could not navigate to video mode, attempting direct generation...")

            time.sleep(1.5)

            # Submit the prompt
            if not _submit_prompt(page, prompt):
                return False

            time.sleep(2)
            log.info("  Prompt submitted, waiting for generation...")
            page.screenshot(path=str(BASE_DIR / "logs" / "gemini_generating.png"))

            # Wait and download
            ok = _wait_and_download(page, output_path, max_wait=max_wait)

        except Exception as e:
            log.error(f"  Unexpected error: {e}")
            try:
                page.screenshot(path=str(BASE_DIR / "logs" / "gemini_exception.png"))
            except Exception:
                pass
            ok = False

        try:
            ctx.close()
        except Exception:
            pass

    return ok


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gemini Web (Omni) video generation")
    parser.add_argument("--prompt", help="Video prompt")
    parser.add_argument("--output", help="Output MP4 path")
    parser.add_argument("--login-only", action="store_true", help="Open browser for manual login")
    parser.add_argument("--max-wait", type=int, default=300, help="Max wait seconds (default 300)")
    args = parser.parse_args()

    if args.login_only:
        sys.exit(0 if login_only() else 1)

    if not args.prompt or not args.output:
        parser.print_help()
        sys.exit(1)

    ok = generate(args.prompt, Path(args.output), max_wait=args.max_wait)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
