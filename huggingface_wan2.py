"""
huggingface_wan2.py — 呼叫 HuggingFace Wan2.1 Space

  - 完全免費、無浮水印（watermark_wan=False）
  - Space: https://wan-ai-wan2-1.hf.space（wan-ai/Wan2.1）
  - 使用 gradio_client 官方 library，自動處理 session / WebSocket
  - 流程：
      1. Client('wan-ai/Wan2.1') → 建立 session
      2. client.predict('/t2v_generation_async') → 觸發生影（返回預估等待時間）
      3. 循環 client.predict('/status_refresh') → 輪詢進度，直到 video 就緒
      4. 下載影片（httpx）

安裝依賴：
  pip install gradio_client httpx

正常生影：
  python huggingface_wan2.py --prompt "..." --output "C:\\YT\\amazon\\output\\clips\\xxx.mp4"

測試：
  python huggingface_wan2.py --test
"""

import sys
import json
import time
import shutil
import argparse
import logging
from pathlib import Path

BASE_DIR = Path(r"C:\projects\YT\amazon")
LOG_FILE = BASE_DIR / "logs" / "daily.log"

HF_SPACE    = "wan-ai/Wan2.1"
HF_SPACE_URL = "https://wan-ai-wan2-1.hf.space"

# 生影參數
SIZE_9_16    = "720*1280"   # 9:16 直向
WATERMARK    = False         # 不要浮水印
DEFAULT_SEED = -1

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [HF-WAN2] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w",
                 encoding="utf-8", errors="replace", closefd=False)
        ),
    ],
)
log = logging.getLogger(__name__)


def _extract_video_from_status(status: list) -> str | None:
    """
    從 status_refresh 輸出中提取影片路徑/URL。

    status_refresh 輸出格式（gradio_client）：
      status[0] = VideoData 或 {'value': None, '__type__': 'update'}
                  有值時: {'value': {'video': {'path': '...', 'url': '...'}, ...}, ...}
      status[1] = Cost Time
      status[2] = Estimated Waiting Time
      status[3] = Progress （{'label': '(N%)...', 'value': N, '__type__': 'update'}）
    """
    if not status or status[0] is None:
        return None

    item = status[0]

    # gradio_client 返回的 update dict
    if isinstance(item, dict):
        value = item.get("value")
        if value is None:
            return None
        # value = {'video': '/local/path/file.mp4'} or {'video': {'path': '...', 'url': '...'}, ...}
        if isinstance(value, dict):
            video_obj = value.get("video")
            if video_obj is not None:
                # gradio_client 自動下載後返回本地路徑字串
                if isinstance(video_obj, str) and video_obj:
                    return video_obj
                if isinstance(video_obj, dict):
                    return video_obj.get("url") or video_obj.get("path")
            # 直接就是 path/url
            return value.get("url") or value.get("path")
        if isinstance(value, str):
            return value

    # 直接的 VideoData dict（不含 __type__）
    if isinstance(item, dict):
        video_obj = item.get("video")
        if isinstance(video_obj, dict):
            return video_obj.get("url") or video_obj.get("path")
        return item.get("url") or item.get("path")

    if isinstance(item, str):
        return item

    return None


def _get_progress(status: list) -> float | None:
    """從 status_refresh 輸出取進度百分比（0-100）。"""
    if not status or len(status) < 4:
        return None
    prog = status[3]
    if isinstance(prog, dict):
        val = prog.get("value")
        if isinstance(val, (int, float)):
            return float(val)
    if isinstance(prog, (int, float)):
        return float(prog)
    return None


def _http_download(url: str, dest: Path) -> bool:
    """用 httpx 下載影片。"""
    try:
        import httpx
    except ImportError:
        log.error("httpx 未安裝！pip install httpx")
        return False
    try:
        with httpx.Client(verify=True, follow_redirects=True,
                          timeout=httpx.Timeout(60.0)) as session:
            with session.stream("GET", url,
                                timeout=httpx.Timeout(None, connect=30)) as r:
                r.raise_for_status()
                dest.write_bytes(r.read())
        size = dest.stat().st_size
        if size < 100_000:
            log.warning(f"  下載過小 ({size} bytes)")
            return False
        log.info(f"  ✓ 下載完成 ({size // 1024} KB)")
        return True
    except Exception as e:
        log.error(f"  下載失敗: {e}")
        return False


def generate(prompt: str, output_path: Path, timeout_s: int = 1200) -> bool:
    """
    呼叫 HuggingFace Wan2.1 生影，儲存到 output_path。
    timeout_s 預設 1200s（20 分鐘），因 Space 高峰期等待可達 10+ 分鐘。

    流程：
      1. 建立 gradio_client（自動管理 session）
      2. predict('/t2v_generation_async') → 觸發，取得預估等待時間
      3. 輪詢 predict('/status_refresh') 直到影片就緒
      4. 下載影片
    """
    try:
        from gradio_client import Client
    except ImportError:
        log.error("gradio_client 未安裝！pip install gradio_client")
        return False

    log.info(f"HuggingFace Wan2.1 生影 | prompt={prompt[:60]}...")
    log.info(f"  size={SIZE_9_16}, watermark={WATERMARK}, seed={DEFAULT_SEED}")

    start_time = time.time()

    # ── 1. 建立 session
    log.info(f"  連接 {HF_SPACE}...")
    try:
        client = Client(HF_SPACE, verbose=False)
        log.info(f"  ✓ Session 建立 | session_hash={client.session_hash[:16]}...")
    except Exception as e:
        log.error(f"  ✗ 無法連接 Space: {e}")
        return False

    # ── 2. 觸發 t2v_generation_async
    log.info("  觸發生影（t2v_generation_async）...")
    try:
        t2v_result = client.predict(
            prompt=prompt,
            size=SIZE_9_16,
            watermark_wan=WATERMARK,
            seed=float(DEFAULT_SEED),
            api_name="/t2v_generation_async",
        )
        # 返回格式: (update_dict_or_None, estimated_wait_secs)
        wait_est = None
        if isinstance(t2v_result, (list, tuple)) and len(t2v_result) >= 2:
            raw_wait = t2v_result[1]
            if isinstance(raw_wait, (int, float)):
                wait_est = raw_wait
        if wait_est:
            log.info(f"  ✓ 已觸發 | 預估等待: {wait_est:.0f}s ({wait_est/60:.1f} 分鐘)")
        else:
            log.info(f"  ✓ 已觸發 | t2v_result={t2v_result}")
    except Exception as e:
        log.error(f"  ✗ t2v_generation_async 失敗: {e}")
        return False

    # ── 3. 輪詢 status_refresh
    poll_count = 0
    last_log   = 0
    log.info(f"  開始輪詢 status_refresh（最多 {timeout_s // 60} 分鐘）...")

    while time.time() - start_time < timeout_s:
        poll_count += 1
        try:
            status = client.predict(api_name="/status_refresh")
        except Exception as e:
            log.warning(f"  status_refresh 第 {poll_count} 次失敗: {e}")
            time.sleep(10)
            continue

        # 顯示進度（只在 0-100 範圍內才是真實百分比，否則是估計等待秒數）
        progress = _get_progress(status)
        elapsed  = int(time.time() - start_time)
        if progress and 0 < progress <= 100:
            log.info(f"  [{elapsed}s] 生成進度: {progress:.0f}% (第 {poll_count} 次輪詢)")
        elif progress and progress > 100:
            log.info(f"  [{elapsed}s] 排隊中，預估剩餘 {progress:.0f}s (第 {poll_count} 次輪詢)")
        elif time.time() - last_log > 30:
            log.info(f"  [{elapsed}s] 生成中... (第 {poll_count} 次輪詢)")
            last_log = time.time()

        # 嘗試提取影片
        video_path = _extract_video_from_status(status)
        if video_path:
            log.info(f"  ✓ 影片就緒！(第 {poll_count} 次輪詢)")
            log.info(f"  影片路徑: {video_path}")

            # ── 4. 下載/複製影片
            output_path.parent.mkdir(parents=True, exist_ok=True)
            src = Path(str(video_path))
            success = False

            if src.exists():
                shutil.copy2(str(src), str(output_path))
                log.info(f"  ✓ 本地複製完成")
                success = True
            elif str(video_path).startswith("/"):
                file_url = f"{HF_SPACE_URL}/gradio_api/file={video_path}"
                log.info(f"  下載: {file_url}")
                success = _http_download(file_url, output_path)
            elif str(video_path).startswith("http"):
                log.info(f"  下載: {video_path}")
                success = _http_download(str(video_path), output_path)
            else:
                file_url = f"{HF_SPACE_URL}/gradio_api/file={video_path}"
                success = _http_download(file_url, output_path)

            if success and output_path.exists() and output_path.stat().st_size > 100_000:
                log.info(
                    f"  ✓ Wan2.1 生影成功: {output_path.name} "
                    f"({output_path.stat().st_size // 1024} KB)"
                )
                return True

            log.error(f"  ✗ 影片下載失敗或過小: {output_path}")
            return False

        time.sleep(12)

    log.error(f"  ✗ 輪詢逾時 ({timeout_s}s / {poll_count} 次)，無法取得影片")
    return False


def run(prompt: str, output_path: Path) -> bool:
    return generate(prompt, output_path)


# ── CLI ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HuggingFace Wan2.1 文字轉影片")
    parser.add_argument("--prompt",  type=str, default="", help="影片描述提示詞")
    parser.add_argument("--output",  type=str, default="", help="輸出 MP4 路徑")
    parser.add_argument("--test",    action="store_true", help="用測試 prompt 驗證完整流程")
    args = parser.parse_args()

    if args.test:
        test_prompt = (
            "A cute orange tabby cat sitting next to a modern automatic pet feeder, "
            "the feeder dispenses kibble, the cat looks excited, "
            "bright clean indoor background, photorealistic, vertical 9:16 video"
        )
        test_output = BASE_DIR / "output" / "clips" / "hf_wan2_test.mp4"
        test_output.parent.mkdir(parents=True, exist_ok=True)
        log.info("=== HuggingFace Wan2.1 測試 ===")
        log.info(f"Prompt: {test_prompt}")
        log.info(f"Output: {test_output}")
        ok = run(test_prompt, test_output)
        if ok:
            size = test_output.stat().st_size // 1024
            log.info(f"✓ 測試成功！檔案: {test_output} ({size} KB)")
        else:
            log.error("✗ 測試失敗")
        sys.exit(0 if ok else 1)

    elif args.prompt and args.output:
        ok = run(args.prompt, Path(args.output))
        sys.exit(0 if ok else 1)

    else:
        print("用法：python huggingface_wan2.py --prompt '...' --output 'xxx.mp4'")
        print("      python huggingface_wan2.py --test")
        sys.exit(1)
