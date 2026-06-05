"""
veo3_browser.py — 用 Playwright 操作 Google Flow 生成 Veo 3 影片
  - 使用 labs.google/fx/tools/flow 的免費 1000 AI點數/月
  - 下載為 ZIP 後自動解壓提取 MP4

首次執行前需登入：
  python veo3_browser.py --login-only

正常生影：
  python veo3_browser.py --prompt "..." --output "C:\\YT\\amazon\\output\\clips\\xxx.mp4"
"""

import sys
import time
import zipfile
import argparse
import logging
import tempfile
from pathlib import Path

from prompt_validator import validate_prompt

BASE_DIR     = Path(r"C:\projects\YT\amazon")
LOG_FILE     = BASE_DIR / "logs" / "daily.log"
CONFIG_FILE  = BASE_DIR / "config" / "flow_config.json"

# Google Flow URL（免費 1000 AI點數）
FLOW_BASE_URL    = "https://labs.google/fx/tools/flow"

# Chrome Profile（自動化專屬，不影響原本 Chrome）
CHROME_PROFILE   = BASE_DIR / "config" / "chrome_profile_aistudio"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [VEO3] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(open(sys.stdout.fileno(), mode='w',
                                   encoding='utf-8', errors='replace',
                                   closefd=False)),
    ],
)
log = logging.getLogger(__name__)


# ── Flow Project URL 管理 ────────────────────────────────────

def _get_project_url() -> str:
    """讀取已儲存的 Flow project URL，沒有就用 base URL。"""
    import json
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text("utf-8"))
            url = cfg.get("flow_project_url", "")
            if url:
                return url
        except Exception:
            pass
    return FLOW_BASE_URL


def _save_project_url(url: str):
    """儲存 Flow project URL 供後續使用。"""
    import json
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text("utf-8"))
        except Exception:
            pass
    cfg["flow_project_url"] = url
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")
    log.info(f"  Flow project URL 已儲存: {url}")


# ── Chrome Context ───────────────────────────────────────────

def get_context(pw, headless: bool = False):
    """建立 persistent Chrome context（自動化專屬 profile）。"""
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    log.info(f"使用自動化 Chrome profile: {CHROME_PROFILE}")
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(CHROME_PROFILE),
        channel="chrome",
        headless=headless,
        slow_mo=50,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-extensions",
            "--disable-sync",
            "--disable-background-networking",
            "--disable-default-apps",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        accept_downloads=True,
        viewport={"width": 1568, "height": 708},
        ignore_default_args=["--enable-automation"],
    )
    return None, ctx


# ── Login Detection ──────────────────────────────────────────

def _is_logged_in(page) -> bool:
    """確認是否已登入 Google Flow。"""
    try:
        url = page.url
        if "accounts.google.com" in url or "signin" in url.lower():
            return False
        if "labs.google" not in url:
            return False
        # 有輸入框或帳號頭像 = 已登入
        checks = [
            page.locator("textarea").count(),
            page.locator("[contenteditable='true']").count(),
            page.locator('[aria-label*="account" i]').count(),
        ]
        return any(c > 0 for c in checks)
    except Exception:
        return False


# ── Login Only ───────────────────────────────────────────────

def login_only():
    """開啟 Flow 讓使用者登入 Google 帳號，登入後永久保留。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("請先執行: pip install playwright && playwright install chromium")
        return False

    log.info("=" * 55)
    log.info("Google Flow 登入模式")
    log.info(f"Profile 路徑: {CHROME_PROFILE}")
    log.info("登入一次後，之後不需要再登入")
    log.info("=" * 55)

    with sync_playwright() as pw:
        _, ctx = get_context(pw, headless=False)
        page = ctx.new_page()
        page.bring_to_front()

        log.info(f"開啟 Flow: {FLOW_BASE_URL}")
        page.goto(FLOW_BASE_URL, wait_until="domcontentloaded", timeout=30000)
        page.bring_to_front()
        time.sleep(4)

        if _is_logged_in(page):
            log.info("  ✓ 已偵測到登入狀態")
            # 儲存 project URL（若已在 project 頁面）
            if "/project/" in page.url:
                _save_project_url(page.url)
            ctx.close()
            return True

        log.warning("=" * 55)
        log.warning("★ 請在彈出的 Chrome 視窗中登入 Google 帳號 ★")
        log.warning("  使用 waynelim1983@gmail.com")
        log.warning("=" * 55)
        page.bring_to_front()

        for i in range(400):  # 最多等 20 分鐘
            time.sleep(3)
            try:
                page.bring_to_front()
            except Exception:
                pass
            if _is_logged_in(page):
                log.info(f"  ✓ 登入成功！({(i+1)*3}s)")
                if "/project/" in page.url:
                    _save_project_url(page.url)
                break
            if i % 5 == 0:
                log.info(f"  等待登入... {page.url[:70]} ({(i+1)*3}s)")
        else:
            log.error("登入逾時（20 分鐘），請重新執行")
            ctx.close()
            return False

        time.sleep(2)
        ctx.close()
        log.info("完成！Flow 登入狀態已儲存")
    return True


# ── ZIP 解壓 → MP4 ───────────────────────────────────────────

def _extract_mp4_from_zip(zip_path: Path, output_path: Path) -> bool:
    """從 ZIP 中提取第一個 .mp4 檔案到 output_path。"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            mp4_files = [f for f in zf.namelist() if f.lower().endswith(".mp4")]
            if not mp4_files:
                log.error(f"ZIP 中找不到 MP4 檔案: {zf.namelist()}")
                return False
            # 取最大的 mp4（通常是主影片）
            mp4_name = max(mp4_files, key=lambda f: zf.getinfo(f).file_size)
            log.info(f"  ZIP 內容: {zf.namelist()}")
            log.info(f"  提取: {mp4_name}")
            data = zf.read(mp4_name)
            output_path.write_bytes(data)
            size_kb = len(data) // 1024
            log.info(f"  ✓ 解壓完成: {output_path.name} ({size_kb} KB)")
            return True
    except Exception as e:
        log.debug(f"ZIP 解壓失敗（可能是直接 MP4，非 ZIP）: {e}")
        return False


# ── Generate ─────────────────────────────────────────────────

def _navigate_to_flow(page) -> bool:
    """
    導航到 Flow，每次都建立新 project，確保從乾淨的 VIDEO 模式開始。
    流程：
      A. about 頁面 → 點 "Create with Flow"
      B. project 列表頁 → 點 "+ 新建項目"（永遠建新 project，不重用舊的）
      C. 已在 project → 確認有輸入框
    """
    log.info(f"導航到 Flow: {FLOW_BASE_URL}")
    page.goto(FLOW_BASE_URL, wait_until="domcontentloaded", timeout=30000)
    time.sleep(4)

    for attempt in range(8):
        url = page.url
        log.info(f"  [step {attempt+1}] URL: {url[:70]}")

        # ── C: 已在 project workspace ─────────────────────
        if "/project/" in url:
            time.sleep(2)
            if page.locator("textarea").count() > 0:
                _save_project_url(url)
                log.info("  ✓ 已在 project workspace")
                return True
            # 在 project 但沒有 textarea，可能在某個 clip 內，退回上層
            try:
                back_btn = page.locator('[aria-label*="back" i], [aria-label*="返回" i], button:has-text("←")').first
                if back_btn.is_visible():
                    back_btn.click()
                    time.sleep(2)
                    continue
            except Exception:
                pass
            time.sleep(2)
            continue

        # ── A: About / landing 頁面 ────────────────────────
        create_btn = page.locator(
            'button:has-text("Create with Flow"), '
            'a:has-text("Create with Flow")'
        )
        if "flow/about" in url or create_btn.count() > 0:
            log.info("  偵測到 about 頁面，點擊 Create with Flow...")
            create_btn.first.click()
            time.sleep(3)
            continue

        # ── B: Project 列表頁 ──────────────────────────────
        if "tools/flow" in url and "/project/" not in url:
            # 先關掉任何彈窗（同意、公告、onboarding 等）
            try:
                for close_sel in [
                    # Google Flow onboarding 同意彈窗「下一步」
                    'button:has-text("下一步")',
                    'button:has-text("Next")',
                    'button:has-text("繼續")',
                    'button:has-text("Continue")',
                    # 一般關閉按鈕
                    'button[aria-label*="close" i]',
                    'button:has-text("完成")',
                    'button:has-text("✕")',
                    '[class*="dismiss"]',
                ]:
                    c = page.locator(close_sel)
                    if c.count() > 0 and c.first.is_visible():
                        c.first.click()
                        log.info(f"  ✓ 關閉彈窗 [{close_sel[:40]}]")
                        time.sleep(1.5)
                        break
            except Exception:
                pass

            # 找 "+ 新建項目" 按鈕（永遠建新 project）
            log.info("  找 + 新建項目 按鈕...")
            new_proj = page.locator(
                'button:has-text("新建项目"), button:has-text("新建項目"), '
                'button:has-text("New project"), button:has-text("新建")'
            )
            if new_proj.count() > 0:
                new_proj.first.click()
                log.info("  ✓ 點擊新建項目")
                time.sleep(4)
                continue

            # 備用：用 JS 找「新建」按鈕
            try:
                found = page.evaluate("""
                    () => {
                        const btns = [...document.querySelectorAll('button')];
                        const newBtn = btns.find(b =>
                            b.textContent.includes('新建') ||
                            b.textContent.includes('New project') ||
                            b.textContent.includes('Create')
                        );
                        if (newBtn) { newBtn.click(); return true; }
                        return false;
                    }
                """)
                if found:
                    log.info("  ✓ JS 找到新建按鈕並點擊")
                    time.sleep(4)
                    continue
            except Exception:
                pass

        time.sleep(2)

    log.error(f"  ✗ 無法進入 Flow project（最終 URL: {page.url}）")
    page.screenshot(path=str(BASE_DIR / "logs" / "flow_nav_fail.png"))
    return False


def _ensure_video_mode(page) -> bool:
    """
    確認 Flow 在影片生成模式（Veo 3.1 Fast）。
    策略：
      1. 若底部工具列有「视频」/「Video」模式按鈕且未選中 → 點擊選中
      2. 若偵測到圖片模式（Nano Banana 標籤） → 點擊開啟模型選擇器 → 選 Veo
      3. 若已顯示 Veo 相關文字 → 直接返回 True
    """
    time.sleep(1.5)

    # ── 策略 1：找工具列的「视频」分頁按鈕 ───────────────
    try:
        # Flow 工具列可能有 "图片" / "视频" 切換 tabs
        video_tab = page.locator(
            'button:has-text("视频"), button:has-text("Video"), '
            'button:has-text("影片"), [role="tab"]:has-text("视频")'
        )
        # 只點擊「視頻」tab（若存在且未選中）
        for i in range(video_tab.count()):
            btn = video_tab.nth(i)
            if btn.is_visible():
                aria = btn.get_attribute("aria-selected") or ""
                cls  = btn.get_attribute("class") or ""
                if aria != "true" and "active" not in cls.lower() and "selected" not in cls.lower():
                    btn.click()
                    log.info("  ✓ 點擊「视频」tab 切換到影片模式")
                    time.sleep(1.5)
                    # 關閉任何可能彈出的 dropdown（按 Escape）
                    page.keyboard.press("Escape")
                    time.sleep(0.5)
                elif aria == "true" or "active" in cls.lower():
                    log.info("  ✓ 已在「视频」tab（影片模式）")
                    # 仍然按 Escape 以防有殘留的 dropdown
                    page.keyboard.press("Escape")
                    time.sleep(0.3)
                    return True
    except Exception as e:
        log.debug(f"  策略1 ({e})")

    # ── 策略 2：偵測 Nano Banana → 切換模型 ──────────────
    if page.locator(':text("Nano Banana")').count() > 0:
        log.info("  偵測到圖片模式（Nano Banana），切換為影片模式...")
        try:
            model_btn = page.locator(':text("Nano Banana")').first
            model_btn.click()
            time.sleep(1.5)

            # 截圖方便 debug
            page.screenshot(path=str(BASE_DIR / "logs" / "flow_model_dropdown.png"))

            # 找 Veo 選項
            veo_opt = page.locator(
                ':text("Veo 3.1 Fast"), :text("Veo 3.1"), '
                ':text("Veo 3"), :text("Veo")'
            )
            if veo_opt.count() > 0:
                veo_opt.first.click()
                time.sleep(1)
                log.info("  ✓ 已切換為 Veo 影片模式")
                return True
            else:
                log.warning("  找不到 Veo 選項（截圖已存）")
                page.screenshot(path=str(BASE_DIR / "logs" / "flow_model_sel.png"))
                return False
        except Exception as e:
            log.warning(f"  切換模式失敗: {e}")
            return False

    # ── 策略 3：已有 Veo 文字 ─────────────────────────────
    if page.locator(':text("Veo")').count() > 0:
        log.info("  ✓ 已在影片生成模式（偵測到 Veo）")
        return True

    # 截圖供 debug，但不阻斷流程
    log.info("  ✓ 未偵測到圖片模式，繼續（預設影片）")
    page.screenshot(path=str(BASE_DIR / "logs" / "flow_mode_check.png"))
    return True


def generate(prompt: str, output_path: Path, max_wait: int = 480) -> bool:
    """
    用 Google Flow 生成影片並下載到 output_path (.mp4)。
    """
    prompt = validate_prompt("veo", prompt)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("請先執行: pip install playwright && playwright install chromium")
        return False

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        _, ctx = get_context(pw, headless=False)
        page = ctx.new_page()

        # 導航到 Flow（自動找到可用 project，不依賴固定 URL）
        if not _navigate_to_flow(page):
            log.error("無法進入 Flow，請確認登入狀態: python veo3_browser.py --login-only")
            ctx.close()
            return False

        # 確認已登入
        if not _is_logged_in(page):
            log.error("Flow 未登入，請先執行: python veo3_browser.py --login-only")
            ctx.close()
            return False

        log.info("  ✓ 已登入 Flow")
        time.sleep(2)

        # ── 確認影片模式（非圖片模式）──────────────────────
        if not _ensure_video_mode(page):
            log.warning("  無法切換到影片模式，繼續嘗試...")

        time.sleep(1)

        # ── 選擇 9:16 直向比例（Shorts 格式）──────────────
        try:
            ratio_btns = page.locator('button[aria-label*="9:16"], button[aria-label*="portrait"], button:has-text("9:16")')
            if ratio_btns.count() > 0:
                ratio_btns.first.click()
                log.info("  ✓ 已選擇 9:16 直向比例")
                time.sleep(0.5)
            else:
                # 嘗試找比例選擇器並點選「縱向/Portrait」選項
                aspect_sel = page.locator('[aria-label*="aspect"], [aria-label*="比例"], [data-aspect]')
                if aspect_sel.count() > 0:
                    aspect_sel.first.click()
                    time.sleep(0.5)
                    portrait_opt = page.locator(':text("9:16"), :text("Portrait"), :text("縱向"), :text("垂直")')
                    if portrait_opt.count() > 0:
                        portrait_opt.first.click()
                        log.info("  ✓ 已透過選擇器設定 9:16")
                        time.sleep(0.5)
                    else:
                        log.info("  （找不到比例選擇器，Flow 預設保持）")
                else:
                    log.info("  （找不到比例按鈕，Flow 預設保持）")
        except Exception as e:
            log.debug(f"  比例選擇略過: {e}")

        time.sleep(1)

        # ── 找到提示詞輸入框（底部工具列）─────────────────
        # Flow 的輸入框在底部（y > 600px），placeholder "您希望创作什么内容？"
        # 不能選 project title（在頂部）
        log.info(f"輸入提示詞: {prompt[:60]}...")

        prompt_box = None

        # 方法A：直接找底部的 contenteditable（y > 550px，容忍不同解析度下的微小偏移）
        try:
            all_ce = page.locator("[contenteditable='true']")
            count = all_ce.count()
            log.info(f"  找到 {count} 個 contenteditable 元素")
            for i in range(count - 1, -1, -1):
                el = all_ce.nth(i)
                if el.is_visible():
                    box = el.bounding_box()
                    if box:
                        log.info(f"    contenteditable[{i}] y={box['y']:.0f} w={box['width']:.0f}")
                        if box["y"] > 550 and box["width"] > 100:
                            prompt_box = el
                            log.info(f"  ✓ 選定輸入框: contenteditable[{i}] y={box['y']:.0f}")
                            break
        except Exception as e:
            log.warning(f"  方法A失敗: {e}")

        # 方法B：用 JS 直接找 placeholder 文字的 div
        if not prompt_box:
            try:
                found = page.evaluate("""
                    () => {
                        const all = [...document.querySelectorAll('[contenteditable="true"]')];
                        for (const el of all.reverse()) {
                            const r = el.getBoundingClientRect();
                            if (r.y > 550 && r.width > 100) {
                                el.setAttribute('data-pw-found', 'yes');
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                if found:
                    prompt_box = page.locator('[contenteditable="true"][data-pw-found="yes"]').first
                    log.info("  ✓ JS找到底部輸入框")
            except Exception as e:
                log.warning(f"  方法B失敗: {e}")

        if not prompt_box:
            log.error("找不到提示詞輸入框（底部 contenteditable）")
            page.screenshot(path=str(BASE_DIR / "logs" / "flow_debug.png"))
            ctx.close()
            return False

        # ── 輸入提示詞（Slate.js 相容：鍵盤事件）──────────────
        # Flow 使用 Slate.js，execCommand 只更新 DOM，不更新 Slate 內部狀態
        # 必須用真實鍵盤事件（keyboard.type）才能讓 React/Slate 正確感知輸入

        # 先按 Escape 關閉任何可能開著的 dropdown/popover
        page.keyboard.press("Escape")
        time.sleep(0.5)

        # 點輸入框讓它聚焦
        prompt_box.click(timeout=10000)
        time.sleep(0.5)

        # 全選清空（先按 Ctrl+A 再 Backspace/Delete，確保 Slate 的 selection 也被清除）
        page.keyboard.press("Control+a")
        time.sleep(0.2)
        page.keyboard.press("Backspace")
        time.sleep(0.2)

        # 用 keyboard.type() 逐字輸入（觸發 Slate 識別的 beforeinput / keydown 事件）
        log.info(f"  keyboard.type() 輸入 {len(prompt)} 字...")
        page.keyboard.type(prompt, delay=15)
        time.sleep(0.5)

        # 驗證文字是否進入 Slate 模型（DOM + Slate textContent 都核對）
        actual_text = page.evaluate("""
            () => {
                const el = [...document.querySelectorAll('[contenteditable="true"]')]
                    .find(e => {
                        const r = e.getBoundingClientRect();
                        return r.y > 600 && r.width > 100;
                    });
                return el ? el.textContent : '';
            }
        """)
        if actual_text and len(actual_text) > 5:
            log.info(f"  ✓ 提示詞已輸入（{len(actual_text)} 字）")
        else:
            log.warning(f"  ⚠ 輸入框仍空（取得: '{actual_text[:30]}'），繼續...")

        time.sleep(0.5)

        # ── 點擊「視頻 → 」生成按鈕 ─────────────────────
        # Flow 底部右側有「视频 □ 1x →」，→ 是視頻生成按鈕
        # 重要：不能用 Enter（Enter 會觸發圖片生成）
        log.info("點擊視頻生成按鈕（→）...")
        page.screenshot(path=str(BASE_DIR / "logs" / "flow_before_generate.png"))

        clicked = False

        # ── 先記錄所有底部按鈕位置（debug）───────────────
        try:
            btn_info = page.evaluate("""
                () => {
                    return [...document.querySelectorAll('button')]
                        .filter(b => {
                            const r = b.getBoundingClientRect();
                            return r.y > 700 && r.width > 0;
                        })
                        .map(b => {
                            const r = b.getBoundingClientRect();
                            return {x: Math.round(r.x), y: Math.round(r.y),
                                    w: Math.round(r.width), right: Math.round(r.right),
                                    text: b.textContent.trim().slice(0, 20),
                                    aria: b.getAttribute('aria-label') || ''};
                        });
                }
            """)
            for b in btn_info:
                log.info(f"  btn: x={b['x']} y={b['y']} right={b['right']} "
                         f"text='{b['text'][:15]}' aria='{b['aria'][:20]}'")
        except Exception as e:
            log.debug(f"  btn debug error: {e}")

        # 方法1：用 Playwright locator 直接找「创建」按鈕並點擊
        # Playwright locator.click() 使用真實滑鼠事件，自動等待 visible+enabled+stable
        try:
            # 找包含「创建」文字的按鈕（button text = "arrow_forward创建"）
            create_btns = page.locator('button').filter(has_text="创建")
            cnt = create_btns.count()
            log.info(f"  找到 {cnt} 個含「创建」的按鈕")
            if cnt > 0:
                # 先檢查最後一個（最右邊的）是否 disabled
                btn_el = create_btns.last
                is_disabled = btn_el.get_attribute("disabled") is not None
                is_visible  = btn_el.is_visible()
                log.info(f"  创建按鈕: visible={is_visible} disabled={is_disabled}")

                # 如果 disabled，等候最多 3 秒（React state 可能還在更新）
                if is_disabled:
                    for _ in range(6):
                        time.sleep(0.5)
                        if btn_el.get_attribute("disabled") is None:
                            log.info("  创建按鈕已啟用")
                            break
                    else:
                        log.warning("  创建按鈕仍然 disabled，嘗試強制點擊")

                # 使用 Playwright locator.click()（真實滑鼠事件）
                btn_el.click(timeout=10000, force=True)
                log.info("  ✓ 方法1：Playwright locator 點擊「创建」按鈕")
                clicked = True
        except Exception as e:
            log.warning(f"  方法1失敗: {e}")

        # 方法2：座標精確點擊（page.mouse.click 真實滑鼠事件）
        if not clicked:
            try:
                # 找最右底部按鈕的座標（不做 JS click，只取位置）
                btn_pos = page.evaluate("""
                    () => {
                        const btnList = [...document.querySelectorAll('button')]
                            .filter(b => {
                                const r = b.getBoundingClientRect();
                                return r.y > window.innerHeight * 0.75 &&
                                       r.width > 0 && r.height > 0;
                            });
                        if (btnList.length === 0) return null;
                        btnList.sort((a, b) => {
                            return b.getBoundingClientRect().right - a.getBoundingClientRect().right;
                        });
                        const btn = btnList[0];
                        const r = btn.getBoundingClientRect();
                        return {
                            x: Math.round(r.x + r.width / 2),
                            y: Math.round(r.y + r.height / 2),
                            text: btn.textContent.trim().slice(0, 30),
                            aria: btn.getAttribute('aria-label') || '',
                            disabled: btn.disabled
                        };
                    }
                """)
                if btn_pos:
                    log.info(f"  找到最右按鈕: ({btn_pos['x']},{btn_pos['y']}) "
                             f"text='{btn_pos['text']}' disabled={btn_pos.get('disabled')}")
                    page.mouse.move(btn_pos["x"], btn_pos["y"])
                    time.sleep(0.3)
                    page.mouse.click(btn_pos["x"], btn_pos["y"])
                    log.info("  ✓ 方法2：mouse.click 座標點擊生成按鈕")
                    clicked = True
            except Exception as e:
                log.warning(f"  方法2失敗: {e}")

        # 方法3：Ctrl+Enter（video mode 下提交快捷鍵）
        if not clicked:
            try:
                prompt_box.click()
                time.sleep(0.2)
                page.keyboard.press("Control+Enter")
                log.info("  ✓ 方法3：Ctrl+Enter 提交")
                clicked = True
            except Exception as e:
                log.warning(f"  方法3失敗: {e}")

        if not clicked:
            log.error("  ✗ 找不到視頻生成按鈕，請截圖檢查 Flow 頁面")
            page.screenshot(path=str(BASE_DIR / "logs" / "flow_btn_fail.png"))
            ctx.close()
            return False

        log.info(f"  ✓ 已送出生成請求")

        # 點擊後立即截圖（確認 UI 狀態）
        time.sleep(1)
        page.screenshot(path=str(BASE_DIR / "logs" / "flow_after_click.png"))
        log.info(f"  截圖已儲存: flow_after_click.png")

        log.info(f"等待 Flow 生成影片（最多 {max_wait} 秒）...")

        # ── 網路回應攔截（必須在偵測迴圈前設定）─────────────
        # flow-content.google/video/... 是生成後的影片 URL（含簽名、限時）
        # 只要 Flow 頁面任何操作（縮圖點擊、播放器載入、下載按鈕）觸發它，就會被捕獲
        captured_video_urls = []
        import re as _re
        def _on_response(resp):
            try:
                ct = resp.headers.get("content-type", "")
                url = resp.url
                # 直接影片回應（video content-type 或 flow-content URL）
                # 排除 gstatic（Flow 的相機動作示範影片，非生成影片）
                if "gstatic" in url:
                    return
                # flow-content.google/image/ 是縮圖，不是影片，排除
                if "flow-content.google" in url and "/image/" in url:
                    return
                if ("video" in ct or "octet-stream" in ct or
                        ".mp4" in url or ".webm" in url or ".mov" in url or
                        "flow-content.google" in url or
                        "storage.googleapis.com" in url):
                    if (url, ct) not in captured_video_urls:
                        captured_video_urls.append((url, ct))
                        log.info(f"  [network] 影片URL擷取: {url[:80]} ({ct})")
                    return
                # labs.google API 回應 → 記錄並解析 JSON 中的影片 URL
                # 只匹配真實的 labs.google/fx 路徑（排除 google-analytics 等其他 Google 域名）
                if "labs.google/fx" in url or "flow-content.google" in url:
                    log.info(f"  [api] {resp.status} {url[:80]} ct={ct[:30]}")
                    if "json" in ct:
                        try:
                            body = resp.text()
                            if "flow-content.google" in body:
                                for m in _re.finditer(
                                        r'https://flow-content\.google[^\s"\'\\><]+', body):
                                    vurl = m.group().rstrip('",;\\')
                                    # 明確排除縮圖：/image/ 路徑是 JPEG 預覽，不是影片
                                    if "/image/" in vurl:
                                        log.debug(f"  [api-json] 跳過縮圖URL: {vurl[:60]}")
                                        continue
                                    if (vurl, "video/mp4") not in captured_video_urls:
                                        captured_video_urls.append((vurl, "video/mp4"))
                                        log.info(f"  [api-json] 提取影片URL: {vurl[:80]}")
                        except Exception as _e_body:
                            log.debug(f"  [api] body讀取失敗: {_e_body}")
            except Exception:
                pass
        page.on("response", _on_response)

        # 同時攔截請求（debug + 收集 flow-content image URL 供推導影片用）
        # 重要：media.getMediaUrlRedirect 的 307 重導向目標就是 flow-content.google/image/UUID
        # 只要把 /image/ 換成 /video/，就是真正的影片下載 URL（signing token 相同）
        captured_content_ids: list[str] = []  # flow-content.google/image/ URLs

        def _on_request(req):
            url = req.url
            if "flow-content" in url or (".mp4" in url and "gstatic" not in url):
                log.info(f"  [request] {url[:100]}")
                # 儲存 image URL 供 /image/ → /video/ 推導
                if "flow-content.google/image/" in url and url not in captured_content_ids:
                    captured_content_ids.append(url)
        page.on("request", _on_request)

        # ── 等待生成 + 後處理完成 ─────────────────────────
        # Flow 生成流程：
        #   Phase 1：Veo 生成影片（clip 卡片出現，thumbnail 顯示 N% 後處理進度）
        #   Phase 2：後處理（N% → 100% → 消失），此後才能下載
        #   Phase 3：<video> 元素出現（preview player），可以下載
        start = time.time()
        video_ready = False
        time.sleep(5)  # 等 5 秒讓頁面穩定

        def _get_pct():
            """取頁面上所有「XX%」文字（包含 Shadow DOM）"""
            try:
                return page.evaluate("""
                    () => {
                        const pcts = new Set();
                        // 方法1：檢查所有 DOM 元素的 innerText（含 Shadow DOM 展平後）
                        const allEls = document.querySelectorAll('*');
                        allEls.forEach(e => {
                            // 只取葉節點（沒有子 element 的）
                            if (e.shadowRoot) {
                                // shadow root 的子元素
                                e.shadowRoot.querySelectorAll('*').forEach(se => {
                                    const t = se.innerText?.trim() || se.textContent?.trim();
                                    if (t && /^\\d+%$/.test(t)) pcts.add(t);
                                });
                            }
                            const t = e.innerText?.trim() || e.textContent?.trim();
                            if (t && /^\\d+%$/.test(t) && e.children.length === 0) pcts.add(t);
                        });
                        return [...pcts];
                    }
                """)
            except Exception:
                return []

        # ── 偵測生成完成 ─────────────────────────────────────
        # Flow 生成流程：
        #   1. 點擊「创建」→ clip 卡片立即出現（0%）
        #   2. Veo 生成並後處理 → 進度從 0% 升到 100% → 消失
        #   3. 下載按鈕可用，<video> 元素載入
        # 注意："0%~N%" 可能在 Shadow DOM 中，TreeWalker 可能無法取得
        # 備用策略：下載按鈕出現後，直接嘗試用 expect_download() 每 30s 重試一次

        pct_appeared  = False
        pct_gone_since = None   # 追蹤 pct 消失時間（連續 25s 消失 → video ready）
        zero_pct_since = None   # 追蹤 0% 持續時間（rate-limit 偵測）
        dl_try_interval = 0     # 上次嘗試下載的時間點
        loop_video_srcs = []    # 偵測迴圈中找到的 <video> src（供下載用）

        def _perf_video_urls():
            """從瀏覽器 Performance API 尋找曾請求的影片 URL（flow-content）"""
            try:
                return page.evaluate("""
                    () => {
                        const entries = performance.getEntriesByType('resource');
                        return entries
                            .map(e => e.name)
                            .filter(u =>
                                u.includes('flow-content.google') ||
                                (u.includes('.mp4') && !u.includes('gstatic')));
                    }
                """)
            except Exception:
                return []

        while time.time() - start < max_wait:
            elapsed = int(time.time() - start)

            try:
                cur_url = page.url

                # 如果頁面跑回 Flow 首頁（離開 project），代表生成沒有成功送出
                if "/project/" not in cur_url and elapsed > 5:
                    log.warning(f"  ⚠ 頁面離開 project（當前: {cur_url[:60]}）")
                    page.screenshot(path=str(BASE_DIR / "logs" / "flow_navigated_away.png"))
                    break

                # 找後處理進度百分比
                pcts = _get_pct()
                pct_values = [int(p.rstrip('%')) for p in pcts if p.rstrip('%').isdigit()]
                max_pct = max(pct_values) if pct_values else -1

                if pct_values:
                    pct_appeared  = True
                    pct_gone_since = None  # pct 又出現了，重置消失計時器

                # 追蹤 0% 是否卡住（rate limit or 生成失敗）
                if max_pct == 0:
                    if zero_pct_since is None:
                        zero_pct_since = time.time()
                    elif time.time() - zero_pct_since > 120:
                        log.warning("  ⚠ 生成進度卡在 0% 超過 120s，可能達到 rate limit，中止等待")
                        page.screenshot(path=str(BASE_DIR / "logs" / "flow_ratelimit.png"))
                        break
                else:
                    zero_pct_since = None  # reset

                # 成功條件 Z：已捕獲影片 URL（response interceptor 或 performance API）
                if not captured_video_urls:
                    perf_urls = _perf_video_urls()
                    if perf_urls:
                        for pu in perf_urls:
                            if pu not in [u for u, _ in captured_video_urls]:
                                captured_video_urls.append((pu, "video/mp4"))
                                log.info(f"  [perf] 找到影片 URL: {pu[:80]}")
                if captured_video_urls:
                    log.info(f"  ✓ 已捕獲影片 URL（{elapsed}s）→ 進入下載")
                    video_ready = True
                    break

                # 找可播放的 <video> 元素（排除 gstatic 相機示範影片）
                video_srcs = page.evaluate("""
                    () => [...document.querySelectorAll('video')]
                          .map(v => v.src || v.currentSrc || '')
                          .filter(s => s.length > 0 && !s.includes('gstatic'))
                """)

                # 成功條件 A：有真實 video src（非 gstatic）
                if video_srcs:
                    log.info(f"  ✓ <video> src 偵測到（{elapsed}s）: {video_srcs[0][:60]}")
                    loop_video_srcs = list(video_srcs)  # 保存供下載用
                    video_ready = True
                    break

                # 成功條件 C：% 超過 80%
                if pct_appeared and max_pct >= 80:
                    log.info(f"  ✓ 後處理 {max_pct}%（{elapsed}s）→ 嘗試下載")
                    video_ready = True
                    break

                # 成功條件 B：pct 曾出現，消失超過 25s → 假設後處理完成
                # 注意：25s 確保條件 A（video 出現 ~35s）有機會先觸發
                if pct_appeared and not pcts:
                    if pct_gone_since is None:
                        pct_gone_since = time.time()
                    elif time.time() - pct_gone_since > 25:
                        log.info(f"  ✓ pct 消失超過 25s（{elapsed}s）→ 嘗試下載")
                        video_ready = True
                        break

                # ── 主動嘗試（每 30s 試一次）──────────────────────
                # 點縮圖 → 若觸發 flow-content 回應，captured_video_urls 會有資料
                # 點下載按鈕 → 同上
                if elapsed > 10 and (elapsed - dl_try_interval) >= 30:
                    dl_try_interval = elapsed
                    log.info(f"  定期下載嘗試（{elapsed}s, pct={pcts or '無'}）...")

                    # --- 嘗試A：點縮圖 ---
                    try:
                        page.mouse.click(150, 200)
                        time.sleep(2)
                        # 網路攔截已設定，若 camera-remix 載入影片則會進 captured_video_urls
                        if captured_video_urls:
                            log.info(f"  縮圖點擊後捕獲影片 URL")
                            video_ready = True
                            break
                        vsrcs = page.evaluate("""
                            () => [...document.querySelectorAll('video')]
                                  .map(v => v.src||v.currentSrc||'')
                                  .filter(s => s && !s.includes('gstatic'))
                        """)
                        if vsrcs:
                            log.info(f"  縮圖點擊後找到 video src: {vsrcs[0][:60]}")
                            video_ready = True
                            break
                        # --- 嘗試A2：在 camera-remix 中點下載 ---
                        dl_btn = page.locator('button:has-text("下载"), button:has-text("下載")').last
                        if dl_btn.count() > 0 and dl_btn.is_visible():
                            log.info("  camera-remix 中點擊下載按鈕...")
                            dl_btn.click()
                            for _ww in range(8):
                                time.sleep(1)
                                if captured_video_urls:
                                    log.info(f"  下載按鈕觸發 URL（{_ww+1}s）")
                                    video_ready = True
                                    break
                            if video_ready:
                                break
                        page.keyboard.press("Escape")
                    except Exception as ea:
                        log.debug(f"  縮圖點擊: {ea}")

                # 每 30 秒截圖
                if elapsed > 0 and elapsed % 30 == 0:
                    page.screenshot(path=str(BASE_DIR / "logs" / f"flow_gen_{elapsed}s.png"))
                    log.info(f"  等待中 ({elapsed}s/{max_wait}s) | pct={pcts or '無'}")
                elif elapsed % 10 == 0:
                    log.info(f"  等待中 ({elapsed}s) | pct={pcts or '無'} max={max_pct}%")

            except Exception as e:
                log.debug(f"  偵測錯誤: {e}")

            time.sleep(5)

        if not video_ready:
            log.error(f"生成逾時（{max_wait}s）")
            page.screenshot(path=str(BASE_DIR / "logs" / "flow_timeout.png"))
            ctx.close()
            return False

        time.sleep(2)

        # ── 下載影片 ──────────────────────────────────────
        log.info("下載影片...")
        page.screenshot(path=str(BASE_DIR / "logs" / "flow_ready_to_download.png"))
        # _on_response 和 captured_video_urls 在偵測迴圈前已設定，此處直接使用

        # ── 策略-1：偵測迴圈中條件 A 已找到 <video> src，直接嘗試下載 ──
        if loop_video_srcs:
            log.info(f"  策略-1：使用偵測迴圈找到的 video src: {loop_video_srcs[0][:60]}")
            for lsrc in loop_video_srcs:
                if lsrc.startswith("blob:"):
                    try:
                        blob_b64 = page.evaluate(f"""
                            async () => {{
                                const resp = await fetch('{lsrc}');
                                const buf = await resp.arrayBuffer();
                                const bytes = new Uint8Array(buf);
                                let bin = '';
                                for (let i = 0; i < bytes.byteLength; i++)
                                    bin += String.fromCharCode(bytes[i]);
                                return btoa(bin);
                            }}
                        """)
                        if blob_b64:
                            import base64 as _b64
                            data = _b64.b64decode(blob_b64)
                            if len(data) > 200000:
                                output_path.parent.mkdir(parents=True, exist_ok=True)
                                output_path.write_bytes(data)
                                log.info(f"  ✓ 策略-1 Blob下載: {len(data)//1024} KB")
                                ctx.close()
                                return True
                    except Exception as _e_m1b:
                        log.debug(f"  策略-1 blob失敗: {_e_m1b}")
                elif lsrc.startswith("http") and "gstatic" not in lsrc:
                    try:
                        import urllib.request as _url_req_m1
                        ck_m1 = ctx.cookies()
                        ck_str_m1 = "; ".join(f"{c['name']}={c['value']}" for c in ck_m1)
                        req_m1 = _url_req_m1.Request(lsrc, headers={
                            "Cookie": ck_str_m1,
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                            "Referer": "https://labs.google/",
                        })
                        with _url_req_m1.urlopen(req_m1, timeout=120) as r_m1:
                            data = r_m1.read()
                        if len(data) > 200000:
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            output_path.write_bytes(data)
                            log.info(f"  ✓ 策略-1 HTTP下載: {len(data)//1024} KB")
                            ctx.close()
                            return True
                    except Exception as _e_m1h:
                        log.debug(f"  策略-1 http失敗: {_e_m1h}")
            log.info("  策略-1：loop_video_srcs 下載失敗，繼續其他策略")

        # ── 策略0c：flow-content /image/ → /video/ 直接推導影片 URL ──────────
        # 原理：media.getMediaUrlRedirect 307 重導向到 /image/UUID?Expires=...
        #       同樣的 UUID + 簽名 token，把 /image/ 換成 /video/ 即為真正影片 URL
        #       此策略不需要點任何按鈕，是最乾淨的下載方式
        if captured_content_ids:
            import urllib.request as _ur_0c
            log.info(f"  策略0c：嘗試 /image/ → /video/ URL 推導（{len(captured_content_ids)} 個）")
            for _img_url_0c in captured_content_ids:
                _vid_url_0c = _img_url_0c.replace("/image/", "/video/")
                try:
                    log.info(f"  策略0c：{_vid_url_0c[:90]}")
                    _req_0c = _ur_0c.Request(_vid_url_0c, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124",
                        "Referer": "https://labs.google/",
                    })
                    with _ur_0c.urlopen(_req_0c, timeout=120) as _r_0c:
                        _d_0c = _r_0c.read()
                    if len(_d_0c) > 200_000:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(_d_0c)
                        log.info(f"  ✓ 策略0c 下載成功: {len(_d_0c) // 1024} KB → {output_path.name}")
                        ctx.close()
                        return True
                    log.debug(f"  策略0c：檔案過小 ({len(_d_0c)} bytes)")
                except Exception as _e_0c:
                    log.debug(f"  策略0c URL 失敗: {_e_0c}")

        # ── 策略0：若偵測迴圈已捕獲影片 URL，直接下載 ──────
        if not captured_video_urls:
            perf_urls_dl = _perf_video_urls()
            for pu in perf_urls_dl:
                if pu not in [u for u, _ in captured_video_urls]:
                    captured_video_urls.append((pu, "video/mp4"))
                    log.info(f"  [perf-dl] 下載前找到影片 URL: {pu[:80]}")

        if captured_video_urls:
            import urllib.request as _url_req0
            ck0 = ctx.cookies()
            ck_str0 = "; ".join(f"{c['name']}={c['value']}" for c in ck0)
            for url0, ct0 in captured_video_urls:
                # 跳過縮圖（image content-type）
                if "image" in ct0 and "video" not in ct0:
                    log.debug(f"  策略0：跳過縮圖 URL: {url0[:60]}")
                    continue
                try:
                    log.info(f"  策略0：從已捕獲 URL 下載: {url0[:80]}")
                    req0 = _url_req0.Request(url0, headers={
                        "Cookie": ck_str0,
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124",
                        "Referer": "https://labs.google/",
                    })
                    with _url_req0.urlopen(req0, timeout=120) as r0:
                        d0 = r0.read()
                    if len(d0) > 200000:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(d0)
                        log.info(f"  ✓ 策略0 下載完成: {len(d0)//1024} KB")
                        ctx.close()
                        return True
                except Exception as e0:
                    log.debug(f"  策略0 URL 失敗: {e0}")

        # ── 先點縮圖開啟 camera-remix 播放器，並等待 <video> 元素載入 ────
        # 重要：flow-content.google/video/... URL 只在 camera-remix view 點擊下載時觸發
        # 且只有在 <video> 元素已載入時，點擊下載按鈕才會觸發網路回應
        log.info("  點擊縮圖開啟 camera-remix 播放器...")
        video_in_remix = []

        for _try_th in range(3):
            try:
                page.mouse.click(150, 200)   # 縮圖大概位置（左側面板）
                time.sleep(1.5)
                # 立即嘗試座標點擊 play_circle (20,124) 觸發影片載入
                # 注意：座標直接點擊比文字匹配更可靠（按鈕文字可能是日文/繁中混用）
                try:
                    page.mouse.click(20, 124)
                    log.info("  座標點擊 play_circle (20,124)")
                except Exception:
                    pass
                # 同時也嘗試文字定位（備用）
                try:
                    play_btns = page.locator(
                        'button:has-text("观看视频"), button:has-text("觀看視頻"), '
                        'button:has-text("観看"), '
                        '[aria-label*="play" i], [aria-label*="watch" i]'
                    )
                    if play_btns.count() > 0 and play_btns.first.is_visible():
                        play_btns.first.click()
                        log.info("  文字定位點擊 play_circle 按鈕")
                except Exception:
                    pass
                # 等最多 30s 讓 <video> 元素出現
                for _wi in range(30):
                    time.sleep(1)
                    video_in_remix = page.evaluate("""
                        () => [...document.querySelectorAll('video')]
                              .map(v => v.src||v.currentSrc||'')
                              .filter(s => s && !s.includes('gstatic'))
                    """)
                    if video_in_remix:
                        log.info(f"  camera-remix 影片已載入（{_wi+1}s）: {video_in_remix[0][:60]}")
                        break
                    # 已捕獲 URL 就直接離開等待
                    if captured_video_urls:
                        log.info(f"  camera-remix 等待中捕獲到 URL（{_wi+1}s）")
                        break
                    # 10s 後如果還沒有，再試一次 play_circle 點擊
                    if _wi == 9:
                        try:
                            page.mouse.click(20, 124)
                            log.info("  再次點擊 play_circle (20,124)（10s 後重試）")
                        except Exception:
                            pass
            except Exception as e_th:
                log.debug(f"  縮圖點擊 try {_try_th+1}: {e_th}")

            if video_in_remix or captured_video_urls:
                break
            if _try_th < 2:
                log.info(f"  嘗試 {_try_th+1}/3：尚未偵測到 video，按 Escape 後重試...")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                time.sleep(3)

        page.screenshot(path=str(BASE_DIR / "logs" / "flow_camera_remix.png"))
        # 若等待中捕獲到 URL，直接下載
        if captured_video_urls and not video_in_remix:
            log.info(f"  camera-remix 等待期間捕獲到 URL，跳至直接下載")
        if video_in_remix:
            log.info(f"  video_in_remix: {video_in_remix}")
            # 若是非 gstatic 的 HTTP src，嘗試直接下載
            for src_early in video_in_remix:
                if src_early.startswith("http") and "gstatic" not in src_early:
                    try:
                        import urllib.request as _url_req_e
                        ck_e = ctx.cookies()
                        ck_str_e = "; ".join(f"{c['name']}={c['value']}" for c in ck_e)
                        req_e = _url_req_e.Request(src_early, headers={
                            "Cookie": ck_str_e,
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                            "Referer": "https://labs.google/",
                        })
                        with _url_req_e.urlopen(req_e, timeout=120) as r_e:
                            d_e = r_e.read()
                        if len(d_e) > 200000:
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            output_path.write_bytes(d_e)
                            log.info(f"  ✓ video src 直接下載完成: {len(d_e)//1024} KB")
                            ctx.close()
                            return True
                    except Exception as e_early:
                        log.debug(f"  src 直接下載失敗: {e_early}")
        else:
            log.info("  camera-remix view 尚無 video src，繼續嘗試下載按鈕...")

        # Debug：列出關鍵按鈕（download, create, play）
        try:
            key_btns = page.evaluate("""
                () => [...document.querySelectorAll('button')]
                    .filter(b => {
                        const r = b.getBoundingClientRect();
                        const t = b.textContent.trim().toLowerCase();
                        return r.width > 0 && r.height > 0 &&
                               (t.includes('下载') || t.includes('download') ||
                                t.includes('创建') || t.includes('play'));
                    })
                    .map(b => ({
                        text: b.textContent.trim().slice(0, 30),
                        x: Math.round(b.getBoundingClientRect().x),
                        y: Math.round(b.getBoundingClientRect().y)
                    }))
            """)
            for b in key_btns:
                log.info(f"  key_btn ({b['x']},{b['y']}) '{b['text'][:25]}'")
        except Exception as e:
            log.debug(f"  button debug: {e}")

        def _save_file(data_bytes, path):
            """儲存檔案並解壓（如果是 ZIP）"""
            import shutil
            path.parent.mkdir(parents=True, exist_ok=True)
            # 先試著解壓（Flow 可能下載 ZIP 包含 MP4）
            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            tmp_path.write_bytes(data_bytes)
            if _extract_mp4_from_zip(tmp_path, path):
                tmp_path.unlink(missing_ok=True)
                return True
            # 否則直接寫出（可能已是 MP4）
            shutil.copy2(str(tmp_path), str(path))
            tmp_path.unlink(missing_ok=True)
            return path.exists() and path.stat().st_size > 200000

        # ── camera-remix 等待後若已捕獲 URL，立即下載（跳過 expect_download 等待）──
        if captured_video_urls:
            import urllib.request as _url_req_mid
            ck_mid = ctx.cookies()
            ck_str_mid = "; ".join(f"{c['name']}={c['value']}" for c in ck_mid)
            for _umid, _ctmid in captured_video_urls:
                # 跳過縮圖 URL（/image/ 路徑 或 image content-type）
                if "/image/" in _umid or ("image" in _ctmid and "video" not in _ctmid):
                    log.debug(f"  策略0b：跳過縮圖 URL: {_umid[:60]}")
                    continue
                try:
                    log.info(f"  策略0b：camera-remix 等待期間捕獲 URL 下載: {_umid[:80]}")
                    _req_mid = _url_req_mid.Request(_umid, headers={
                        "Cookie": ck_str_mid,
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124",
                        "Referer": "https://labs.google/",
                    })
                    with _url_req_mid.urlopen(_req_mid, timeout=120) as _rmid:
                        _dmid = _rmid.read()
                    if len(_dmid) > 200000:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(_dmid)
                        log.info(f"  ✓ 策略0b 下載完成: {len(_dmid)//1024} KB")
                        ctx.close()
                        return True
                except Exception as _emid:
                    log.debug(f"  策略0b URL 失敗: {_emid}")

        # ── 策略1b：先離開 camera-remix，在 clip card 上懸停找下載按鈕 ────
        # Flow 生成後，clip card 會出現在左側面板，hover 後顯示操作按鈕
        try:
            page.keyboard.press("Escape")
            time.sleep(1)

            # 找所有下載相關按鈕（廣義 selector：aria-label / title / text 包含 download）
            dl_broad = page.locator(
                '[aria-label*="download" i], [aria-label*="下载" i], [aria-label*="下載" i], '
                '[title*="download" i], [title*="下载" i], '
                'button:has-text("下载"), button:has-text("下載"), '
                'button:has-text("Download"), '
                'a[download]'
            )
            cnt_broad = dl_broad.count()
            log.info(f"  策略1b：找到 {cnt_broad} 個下載相關元素")

            if cnt_broad > 0:
                for _i_dl in range(min(cnt_broad, 3)):
                    try:
                        _dl_el = dl_broad.nth(_i_dl)
                        if _dl_el.is_visible():
                            log.info(f"  策略1b：嘗試第 {_i_dl+1} 個下載按鈕...")
                            with page.expect_download(timeout=30000) as _dl_info:
                                _dl_el.click(force=True)
                            _dl_tmp = Path(tempfile.mktemp(suffix=".zip"))
                            _dl_info.value.save_as(str(_dl_tmp))
                            log.info(f"  ✓ 策略1b 下載完成: {_dl_tmp.stat().st_size//1024} KB")
                            if _save_file(_dl_tmp.read_bytes(), output_path):
                                _dl_tmp.unlink(missing_ok=True)
                                ctx.close()
                                return True
                            _dl_tmp.unlink(missing_ok=True)
                    except Exception as _e1b:
                        log.debug(f"  策略1b element {_i_dl}: {_e1b}")

            # 懸停 clip card 位置觸發 hover 按鈕
            for _hx, _hy in [(150, 200), (120, 180), (180, 220)]:
                page.mouse.move(_hx, _hy)
                time.sleep(0.8)
                _dl_hover = page.locator(
                    '[aria-label*="download" i], [aria-label*="下载" i], '
                    'button:has-text("下载"), button:has-text("下載"), '
                    'button:has-text("Download")'
                )
                if _dl_hover.count() > 0 and _dl_hover.first.is_visible():
                    log.info(f"  策略1b：hover ({_hx},{_hy}) 觸發下載按鈕")
                    try:
                        with page.expect_download(timeout=30000) as _dl_h:
                            _dl_hover.first.click(force=True)
                        _dl_hp = Path(tempfile.mktemp(suffix=".zip"))
                        _dl_h.value.save_as(str(_dl_hp))
                        if _save_file(_dl_hp.read_bytes(), output_path):
                            _dl_hp.unlink(missing_ok=True)
                            ctx.close()
                            return True
                        _dl_hp.unlink(missing_ok=True)
                    except Exception as _e1bh:
                        log.debug(f"  策略1b hover: {_e1bh}")

        except Exception as e1b_outer:
            log.debug(f"  策略1b 外層: {e1b_outer}")

        # ── 策略1：用 page.expect_download() 攔截 + 點擊下載按鈕 ────
        dl_btn = page.locator('button:has-text("下载"), button:has-text("下載")').first
        if dl_btn.count() > 0 and dl_btn.is_visible():
            log.info("  策略1：expect_download() + 點擊「下载」按鈕")
            try:
                with page.expect_download(timeout=30000) as dl_info:
                    dl_btn.click()
                dl = dl_info.value
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                    zip_path = Path(tmp.name)
                dl.save_as(str(zip_path))
                log.info(f"  ✓ 策略1 下載完成: {zip_path.stat().st_size//1024} KB")
                if _save_file(zip_path.read_bytes(), output_path):
                    zip_path.unlink(missing_ok=True)
                    ctx.close()
                    return True
                zip_path.unlink(missing_ok=True)
            except Exception as e1:
                log.warning(f"  策略1 失敗: {e1}")

        # ── 策略2：座標點擊下載按鈕 + 等 URL / 處理下拉選單 ────
        log.info("  策略2：座標點擊 (972,88) + 網路 URL 攔截")
        try:
            page.mouse.click(972, 88)  # 下載按鈕的已知座標
            time.sleep(1)
            page.screenshot(path=str(BASE_DIR / "logs" / "flow_after_dl_click.png"))
            # 檢查是否出現下拉選單（含「下载」或「ZIP」的新按鈕）
            try:
                dropdown_btns = page.evaluate("""
                    () => [...document.querySelectorAll('li, [role="menuitem"], [role="option"], a')]
                        .filter(b => {
                            const t = b.textContent.trim().toLowerCase();
                            return (t.includes('下载') || t.includes('zip') ||
                                    t.includes('download') || t.includes('mp4')) &&
                                   b.getBoundingClientRect().width > 0;
                        })
                        .map(b => ({
                            text: b.textContent.trim().slice(0, 30),
                            x: Math.round(b.getBoundingClientRect().x + b.getBoundingClientRect().width/2),
                            y: Math.round(b.getBoundingClientRect().y + b.getBoundingClientRect().height/2)
                        }))
                """)
                if dropdown_btns:
                    log.info(f"  下拉選單: {dropdown_btns}")
                    # 點擊第一個選項
                    first_opt = dropdown_btns[0]
                    page.mouse.click(first_opt['x'], first_opt['y'])
                    log.info(f"  點擊選單項: ({first_opt['x']},{first_opt['y']}) '{first_opt['text']}'")
                    time.sleep(1)
            except Exception as ed:
                log.debug(f"  下拉選單偵測: {ed}")

            # 等最多 15s 讓網路請求觸發
            for _ in range(15):
                if captured_video_urls:
                    break
                time.sleep(1)
            log.info(f"  擷取到 {len(captured_video_urls)} 個影片 URL")
        except Exception as e2:
            log.debug(f"  策略2 點擊: {e2}")

        # 若有擷取到 URL，用 requests 下載
        if captured_video_urls:
            import urllib.request as _url_req
            cookies = ctx.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            for url, ct in captured_video_urls:
                try:
                    log.info(f"  從網路 URL 下載: {url[:80]}")
                    req = _url_req.Request(url, headers={
                        "Cookie": cookie_str,
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124",
                        "Referer": "https://labs.google/",
                    })
                    with _url_req.urlopen(req, timeout=120) as resp:
                        data = resp.read()
                    if len(data) > 200000 and _save_file(data, output_path):
                        log.info(f"  ✓ 網路 URL 下載完成: {len(data)//1024} KB")
                        ctx.close()
                        return True
                except Exception as eu:
                    log.debug(f"  URL 下載失敗: {eu}")

        # ── 策略3：點擊影片縮圖，讓播放器載入，再取 video src ────
        log.info("  策略3：確認播放器已開啟，取 video src")
        try:
            # 若前面縮圖點擊未開啟播放器，再點一次
            cur_vsrcs = page.evaluate("""
                () => [...document.querySelectorAll('video')]
                      .map(v => v.src||v.currentSrc||'').filter(s=>s)
            """)
            if not cur_vsrcs:
                log.info("  策略3：重新點擊縮圖...")
                page.mouse.click(150, 200)
                time.sleep(2)
            all_video_srcs = page.evaluate("""
                () => [...document.querySelectorAll('video')]
                      .map(v => ({src: v.src || v.currentSrc || '', readyState: v.readyState}))
                      .filter(v => v.src.length > 0)
            """)
            log.info(f"  找到 video srcs: {all_video_srcs}")
            for vsrc in all_video_srcs:
                src = vsrc['src']
                if src.startswith("blob:"):
                    # Blob URL：用 JS fetch 讀取
                    log.info(f"  blob URL 下載: {src[:60]}")
                    blob_b64 = page.evaluate(f"""
                        async () => {{
                            const resp = await fetch('{src}');
                            const buf = await resp.arrayBuffer();
                            const bytes = new Uint8Array(buf);
                            let bin = '';
                            for (let i = 0; i < bytes.byteLength; i++) bin += String.fromCharCode(bytes[i]);
                            return btoa(bin);
                        }}
                    """)
                    if blob_b64:
                        import base64
                        data = base64.b64decode(blob_b64)
                        if len(data) > 200000 and _save_file(data, output_path):
                            log.info(f"  ✓ Blob 下載完成: {len(data)//1024} KB")
                            ctx.close()
                            return True
                elif src.startswith("http"):
                    import urllib.request as _url_req
                    cookies = ctx.cookies()
                    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                    req = _url_req.Request(src, headers={
                        "Cookie": cookie_str,
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        "Referer": "https://labs.google/",
                    })
                    with _url_req.urlopen(req, timeout=120) as resp:
                        data = resp.read()
                    if len(data) > 200000 and _save_file(data, output_path):
                        log.info(f"  ✓ HTTP 下載完成: {len(data)//1024} KB")
                        ctx.close()
                        return True
        except Exception as e3:
            log.warning(f"  策略3 失敗: {e3}")

        ctx.close()
        return False


# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Google Flow Veo 3 瀏覽器自動生影")
    parser.add_argument("--login-only", action="store_true", help="只做登入")
    parser.add_argument("--set-project", type=str, help="設定 Flow project URL")
    parser.add_argument("--prompt",  type=str, help="影片提示詞")
    parser.add_argument("--output",  type=str, help="輸出 mp4 路徑")
    args = parser.parse_args()

    if args.login_only:
        login_only()
    elif args.set_project:
        _save_project_url(args.set_project)
        print(f"Flow project URL 已設定: {args.set_project}")
    elif args.prompt and args.output:
        ok = generate(args.prompt, Path(args.output))
        sys.exit(0 if ok else 1)
    else:
        print("用法：")
        print("  python veo3_browser.py --login-only")
        print(f"  python veo3_browser.py --set-project \"https://labs.google/fx/zh/tools/flow/project/XXX\"")
        print('  python veo3_browser.py --prompt "..." --output "C:\\YT\\...\\video.mp4"')
