"""
gemini_browser.py — 用 Playwright 操作 Gemini 動態生成影片 prompt

  - 共用 chrome_profile_aistudio（與 veo3_browser.py 同一 Google session，不需重新登入）
  - 每次生成都是全新故事結構，解決靜態 template 多樣性不足的問題
  - 失敗時自動 fallback（呼叫方決定）

使用：
  python gemini_browser.py                           # 用內建測試產品驗證
  python gemini_browser.py --login-only              # 首次：確認 Google 已登入
  python gemini_browser.py --product '{"name":".."}'# 單一產品生成（供外部呼叫）

安裝依賴：
  pip install playwright && playwright install chromium
"""

import re
import sys
import json
import time
import argparse
import logging
from pathlib import Path

BASE_DIR      = Path(r"C:\projects\YT\amazon")
LOG_FILE      = BASE_DIR / "logs" / "daily.log"
CHROME_PROFILE = BASE_DIR / "config" / "chrome_profile_aistudio"  # 共用 Veo3 session
GEMINI_URL    = "https://gemini.google.com"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GEMINI] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w",
                 encoding="utf-8", errors="replace", closefd=False)
        ),
    ],
)
log = logging.getLogger(__name__)

# ── Prompt 請求模板 ─────────────────────────────────────────────
_REQUEST_TEMPLATE = """\
Product: {name}
Category: {category}
Key feature: {key_feature}
Color: {color}

Write a cinematic scene description for a vertical 9:16 cat product short clip.
Requirements:
- Specific story-driven cat behavior (not generic)
- Include: scene/setting, lighting mood, camera movement (e.g. slow dolly-in, tracking shot)
- 2-3 sentences, 60-100 words, English only

CRITICAL: Output ONLY the scene description text itself.
Do NOT start with "Here is", "Sure", "Certainly", or any intro.
Do NOT add a title, label, or "Prompt:" prefix.
Begin directly with the scene.\
"""


def _build_request(product: dict) -> str:
    return _REQUEST_TEMPLATE.format(
        name        = product.get("name", "smart cat device"),
        category    = product.get("category", "lifestyle"),
        key_feature = product.get("key_feature", "automated smart feature"),
        color       = product.get("color", "white"),
    )


# ── 核心：瀏覽器自動化 ──────────────────────────────────────────

def generate_prompt(product: dict, timeout_s: int = 90) -> str | None:
    """
    開啟 Gemini 網頁，輸入產品資訊，回傳生成的 prompt 字串。
    失敗回傳 None（由呼叫方 fallback 到靜態 template）。
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.error("playwright 未安裝！pip install playwright && playwright install chromium")
        return None

    request_text = _build_request(product)
    log.info(f"Gemini 動態 prompt | {product.get('name', '')[:40]}...")

    with sync_playwright() as p:
        CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
        ctx = p.chromium.launch_persistent_context(
            user_data_dir = str(CHROME_PROFILE),
            channel       = "chrome",          # 使用系統 Chrome，共用 Veo3 session
            headless      = False,
            slow_mo       = 50,
            args          = [
                "--disable-blink-features=AutomationControlled",
                "--disable-extensions",
                "--disable-sync",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            ignore_default_args = ["--enable-automation"],
            viewport      = {"width": 1400, "height": 900},
            ignore_https_errors = True,
        )
        page = ctx.new_page()
        try:
            page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(3)

            # ── 關閉可能的歡迎彈窗 / overlay
            for _ in range(3):
                page.keyboard.press("Escape")
                time.sleep(0.5)
            # 嘗試點掉「Got it」/ 「Close」按鈕
            for dismiss_sel in [
                "button[aria-label*='Close' i]",
                "button[aria-label*='Dismiss' i]",
                "button[aria-label*='Got it' i]",
                ".dismiss-button",
                "[data-dismiss]",
            ]:
                try:
                    btn = page.query_selector(dismiss_sel)
                    if btn:
                        btn.click()
                        time.sleep(0.5)
                except Exception:
                    pass
            time.sleep(1)

            # ── 找輸入框（按優先序嘗試多個 selector）
            input_sel = _find_selector(page, [
                "rich-textarea .ql-editor",
                "div.ql-editor[contenteditable='true']",
                "div[contenteditable='true'][data-placeholder]",
                "div[contenteditable='true']",
                "textarea",
            ], timeout_ms=6000)

            if not input_sel:
                log.error("  找不到 Gemini 輸入框（可能需要 --login-only 重新登入）")
                return None

            # JS focus 繞過 overlay 攔截，再 click
            try:
                page.evaluate(f"document.querySelector(\"{input_sel}\").focus()")
                time.sleep(0.3)
            except Exception:
                pass
            page.click(input_sel, force=True)   # force=True 忽略 overlay 遮擋
            time.sleep(0.3)
            page.keyboard.type(request_text, delay=15)
            time.sleep(0.5)
            page.keyboard.press("Enter")
            log.info("  已送出，等待 Gemini 回應...")

            # ── 等待串流完成，擷取回應
            result = _extract_response(page, timeout_s=timeout_s)
            if result:
                # 偵測 Gemini 誤觸自身影片/圖片生成功能的無效回應
                _invalid = ["generating your video", "check back to see when",
                            "could take a few minutes", "generating an image",
                            "i cannot generate", "i'm unable to"]
                if any(p in result.lower() for p in _invalid):
                    log.warning("  Gemini 誤觸生成功能（非文字回應），回傳 None")
                    return None
                log.info(f"  ✓ 取得 prompt ({len(result)} chars): {result[:70]}...")
            else:
                log.warning("  Gemini 回應擷取失敗")
            return result

        except Exception as e:
            log.error(f"  Gemini 瀏覽器例外: {e}")
            return None
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def _find_selector(page, selectors: list[str], timeout_ms: int = 5000) -> str | None:
    """依序嘗試多個 CSS selector，回傳第一個找到的。"""
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
    except ImportError:
        return None
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=timeout_ms)
            return sel
        except Exception:
            continue
    return None


def _extract_response(page, timeout_s: int = 90) -> str | None:
    """
    等待 Gemini 串流結束，擷取最後一條 model 回應的純文字。
    策略：監看回應文字長度，連續 3 秒不變則視為完成。
    """
    # 先等回應容器出現
    resp_sel = _find_selector(page, [
        "model-response",
        ".model-response-text",
        "message-content",
        "[data-message-author-role='model']",
        ".response-content",
    ], timeout_ms=20_000)

    deadline = time.time() + timeout_s
    prev_text = ""
    stable_ticks = 0  # 每 tick = 2s

    while time.time() < deadline:
        time.sleep(2)
        text = _get_last_response_text(page, resp_sel)
        if not text:
            continue
        if text == prev_text and len(text) > 30:
            stable_ticks += 1
            if stable_ticks >= 2:   # 連續 4 秒穩定 → 串流結束
                return _clean_response(text)
        else:
            stable_ticks = 0
        prev_text = text

    # 超時：回傳現有內容（若夠長）
    if prev_text and len(prev_text) > 30:
        return _clean_response(prev_text)
    return None


def _get_last_response_text(page, resp_sel: str | None) -> str:
    """擷取頁面上最後一條 model 回應的文字。"""
    selectors_to_try = []
    if resp_sel:
        selectors_to_try.append(resp_sel)
    selectors_to_try += [
        "model-response",
        ".model-response-text",
        "message-content",
        "[data-message-author-role='model']",
        ".markdown",
        "p",
    ]
    for sel in selectors_to_try:
        try:
            elements = page.query_selector_all(sel)
            if elements:
                text = elements[-1].inner_text().strip()
                if len(text) > 20:
                    return text
        except Exception:
            continue
    return ""


def _clean_response(text: str) -> str:
    """移除 Gemini 可能附加的引號、標題、前綴、多餘空白。"""
    text = text.strip()

    # 移除 "Gemini 說了 " / "Gemini said " 等前綴
    for prefix in ["Gemini 說了 ", "Gemini said ", "Gemini: ", "Gemini:"]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()

    # 移除 **Title:** 區塊（只留 scene description）
    text = re.sub(r'\s*\*{0,2}[Tt]itle[:\*]+\s*.{0,150}$', '', text,
                  flags=re.MULTILINE).strip()

    lines = text.splitlines()

    # 移除開頭的說明行
    # 修復：若說明行包含 ": " 後的實質內容，保留冒號後的部分而非整行刪除
    INTRO_PREFIXES = (
        "here", "prompt:", "sure", "certainly", "of course",
        "here's", "here is", "below is", "output:",
        "i've", "i have", "let me", "the following",
    )
    while lines:
        stripped = lines[0].strip()
        if not stripped:            # 空行：跳過
            lines.pop(0)
            continue
        lower = stripped.lower().rstrip(":")
        if not lower.startswith(INTRO_PREFIXES):
            break                   # 正常內容行，停止
        # 是說明行 — 嘗試取冒號後的實質內容
        colon_idx = stripped.find(": ")
        if colon_idx > 0:
            rest = stripped[colon_idx + 2:].strip()
            if len(rest) > 30:      # 冒號後有足夠長的實質內容
                lines[0] = rest
                break
        lines.pop(0)                # 純說明行，整行丟棄

    # 移除行首 "**Prompt:**" / "Prompt:" 標籤
    cleaned = [re.sub(r'^\*{0,2}[Pp]rompt[:\*]+\s*', '', ln) for ln in lines]

    result = " ".join(" ".join(cleaned).split())

    # 移除前後引號
    if len(result) > 2 and result[0] in ('"', '“', '「') and result[-1] in ('"', '”', '」'):
        result = result[1:-1]

    return result.strip()


# ── CLI ────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini 動態影片 prompt 生成")
    parser.add_argument("--product",    type=str, help="產品 JSON 字串")
    parser.add_argument("--login-only", action="store_true",
                        help="只開啟瀏覽器確認 Google 登入狀態（通常不需要，共用 Veo3 session）")
    args = parser.parse_args()

    if args.login_only:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("playwright 未安裝！pip install playwright && playwright install chromium")
            sys.exit(1)
        log.info(f"開啟瀏覽器（{CHROME_PROFILE}），確認 Google 帳號登入狀態...")
        with sync_playwright() as p:
            CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(CHROME_PROFILE),
                channel="chrome",
                headless=False,
            )
            page = ctx.new_page()
            page.goto(GEMINI_URL)
            log.info("確認已登入後，關閉瀏覽器即可。")
            input("按 Enter 關閉...")
            ctx.close()
        sys.exit(0)

    if args.product:
        try:
            product = json.loads(args.product)
        except json.JSONDecodeError as e:
            log.error(f"--product JSON 解析失敗: {e}")
            sys.exit(1)
        result = generate_prompt(product)
        if result:
            print(result)
            sys.exit(0)
        sys.exit(1)

    # ── 內建測試
    log.info("=== Gemini 動態 Prompt 測試 ===")
    test_products = [
        {
            "name": "PETKIT PuraMax 2 Self-Cleaning Litter Box",
            "category": "litter_box",
            "key_feature": "auto-rotating drum that cleans in under 60 seconds",
            "color": "white", "size": "large",
        },
        {
            "name": "PETLIBRO Automatic Cat Feeder",
            "category": "smart_feeder",
            "key_feature": "6-meal programmable dispenser with voice recording",
            "color": "beige", "size": "standard",
        },
    ]
    for i, prod in enumerate(test_products, 1):
        log.info(f"\n── 測試 {i}: {prod['name'][:40]}")
        result = generate_prompt(prod)
        if result:
            print(f"\n[OK] Prompt {i}:\n{result}\n")
        else:
            print(f"\n[FAIL] 測試 {i} 失敗（將 fallback 到靜態 template）\n")
