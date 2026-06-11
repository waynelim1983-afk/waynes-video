"""
omni_browser.py — Google Flow Omni Flash 影片生成（Veo3 備援）

同樣使用 labs.google/fx/tools/flow，只是模型選 Omni Flash。
Omni Flash: 30cr/10s，約 33 支/1000cr（比 Veo3.1 Fast 多 66% 片數）。

Usage:
  python omni_browser.py --prompt "..." --output "output/clips/xxx.mp4"
  python omni_browser.py --login-only   # 共用 veo3_browser 的登入 session
"""

import sys
import time
import logging
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "logs" / "daily.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [OMNI] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w",
                 encoding="utf-8", errors="replace", closefd=False)
        ),
    ],
)
log = logging.getLogger(__name__)


# ── Omni Flash 模型選擇（替換 veo3_browser._ensure_video_mode）──────────────

def _ensure_omni_flash_mode(page) -> bool:
    """
    確認 Flow 已選擇 Omni Flash 模型。
    策略：
      1. 確認在「视频」tab
      2. 若已偵測到 Omni Flash → 直接返回 True
      3. 若偵測到其他模型（Veo / Nano Banana）→ 點開選擇器 → 選 Omni Flash
    """
    time.sleep(1.5)

    # ── 策略 1：確認在影片 tab ──────────────────────────────
    try:
        video_tab = page.locator(
            'button:has-text("视频"), button:has-text("Video"), '
            'button:has-text("影片"), [role="tab"]:has-text("视频")'
        )
        for i in range(video_tab.count()):
            btn = video_tab.nth(i)
            if btn.is_visible():
                aria = btn.get_attribute("aria-selected") or ""
                cls  = btn.get_attribute("class") or ""
                if aria != "true" and "active" not in cls.lower() and "selected" not in cls.lower():
                    btn.click()
                    log.info("  ✓ 點擊「视频」tab")
                    time.sleep(1.5)
                    page.keyboard.press("Escape")
                    time.sleep(0.5)
                else:
                    page.keyboard.press("Escape")
                    time.sleep(0.3)
                break
    except Exception as e:
        log.debug(f"  策略1 ({e})")

    # ── 策略 2：已偵測到 Omni Flash → 直接返回 ─────────────
    if page.locator(':text("Omni Flash"), :text("Omni")').count() > 0:
        log.info("  ✓ Omni Flash 模型已選中")
        return True

    # ── 策略 3：找並點開模型選擇器 → 選 Omni Flash ─────────
    log.info("  嘗試選擇 Omni Flash 模型...")
    try:
        # 可能的模型觸發元素（現有模型名稱 = 按鈕）
        trigger_sels = [
            ':text("Nano Banana")',
            ':text("Veo 3.1 Fast")',
            ':text("Veo 3.1 Lite")',
            ':text("Veo 3.1 Quality")',
            ':text("Veo 3.1")',
            ':text("Veo 3")',
            ':text("Veo")',
            '[aria-label*="model" i]',
            '[aria-label*="模型" i]',
        ]
        triggered = False
        for sel in trigger_sels:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click()
                log.info(f"  ✓ 點擊模型選擇器 [{sel}]")
                time.sleep(1.5)
                page.screenshot(path=str(BASE_DIR / "logs" / "omni_model_dropdown.png"))
                triggered = True
                break

        if not triggered:
            # 備援：用 JS 找包含 Veo 文字的可點擊元素
            clicked = page.evaluate("""
                () => {
                    const all = [...document.querySelectorAll('button, [role="button"], [class*="model"]')];
                    const t = all.find(el =>
                        el.textContent.includes('Veo') ||
                        el.textContent.includes('Nano Banana') ||
                        el.textContent.includes('Omni')
                    );
                    if (t) { t.click(); return t.textContent.trim().slice(0,30); }
                    return null;
                }
            """)
            if clicked:
                log.info(f"  ✓ JS 點擊模型觸發 [{clicked}]")
                time.sleep(1.5)
                triggered = True

        if not triggered:
            log.warning("  找不到模型選擇器，繼續（使用現有模型）")
            return True  # 不阻斷流程，讓 Flow 用預設模型繼續

        # 現在應該有下拉選單 → 找 Omni Flash
        omni_opt = page.locator(
            ':text("Omni Flash"), :text("Omni"), '
            '[data-value*="omni" i], [value*="omni" i]'
        )
        if omni_opt.count() > 0:
            omni_opt.first.click()
            time.sleep(1)
            log.info("  ✓ 已選擇 Omni Flash 模型")
            return True
        else:
            log.warning("  找不到 Omni Flash 選項，截圖已存")
            page.screenshot(path=str(BASE_DIR / "logs" / "omni_model_sel.png"))
            # 按 Escape 關閉 dropdown，不阻斷流程
            page.keyboard.press("Escape")
            return False

    except Exception as e:
        log.warning(f"  Omni Flash 選擇失敗: {e}")
        return False


# ── Generate（monkey-patch veo3_browser._ensure_video_mode）─────────────────

def generate(prompt: str, output_path, max_wait: int = 540) -> bool:
    """
    用 Omni Flash 在 Google Flow 生成影片。
    直接 import veo3_browser 並替換模型選擇函數，其餘流程完全相同。
    """
    import veo3_browser as _veo3

    # 讓 veo3_browser 的 log/截圖也落到 smartcat 的目錄
    _veo3.BASE_DIR = BASE_DIR
    _veo3.LOG_FILE = LOG_FILE

    # Monkey-patch：替換模型選擇邏輯
    original = _veo3._ensure_video_mode
    _veo3._ensure_video_mode = _ensure_omni_flash_mode
    try:
        ok = _veo3.generate(prompt, output_path, max_wait=max_wait)
    finally:
        _veo3._ensure_video_mode = original  # 還原（避免影響同進程中的 Veo3）
    return ok


def login_only() -> bool:
    """共用 veo3_browser 的登入 session（同一個 Chrome profile）。"""
    import veo3_browser as _veo3
    _veo3.BASE_DIR = BASE_DIR
    return _veo3.login_only()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Omni Flash (Google Flow) 影片生成")
    parser.add_argument("--prompt", help="影片提示詞")
    parser.add_argument("--output", help="輸出 MP4 路徑")
    parser.add_argument("--login-only", action="store_true",
                        help="只開啟登入畫面（共用 veo3_browser 的 session）")
    args = parser.parse_args()

    if args.login_only:
        sys.exit(0 if login_only() else 1)

    if not args.prompt or not args.output:
        parser.print_help()
        sys.exit(1)

    ok = generate(args.prompt, Path(args.output))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
