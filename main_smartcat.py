"""
main_smartcat.py — AI Video Generation Pipeline

Fallback chain (tried in order, stops at first success):
  1. Veo3 Browser      — Google Flow, 1000 pts/month (primary)
  2. Kling AI          — klingai.com, daily free credits, watermark
  3. OiiOii            — Seedance 2.0 Pro, STAR tokens required
  4. HuggingFace Wan2.1 — fully free, no watermark (queue wait ~8-12 min)

Prompt can optionally be enhanced via Gemini browser (USE_GEMINI_PROMPT=True).
Grok browser is available as an alternative prompt generator (grok_browser.py).

Usage:
  python main_smartcat.py --prompt "A cat playing with a robot toy"
  python main_smartcat.py --prompt "..." --count 3            # serial, 3 videos
  python main_smartcat.py --prompt "..." --count 3 --parallel # parallel via HuggingFace
  python main_smartcat.py --recover                           # recover unprocessed clips
"""

import sys
import time
import logging
import argparse
import datetime
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Paths ────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
LOG_FILE  = BASE_DIR / "logs" / "daily.log"
CLIPS_DIR = BASE_DIR / "output" / "clips"

sys.path.insert(0, str(BASE_DIR))
from quota_tracker    import record, status_str, videos_left
from prompts_smartcat import get_prompt_for_product_hf

# ── Optional: Gemini-enhanced prompt generation ──────────────
# Set True to use gemini_browser.py for richer, dynamic prompts.
# Requires a logged-in Chrome session for Google AI Studio.
USE_GEMINI_PROMPT = False


def _enhance_prompt(prompt: str) -> str:
    """
    Optionally enhance the prompt via Gemini browser automation.
    Falls back to the original prompt on failure or when disabled.
    """
    if USE_GEMINI_PROMPT:
        try:
            from gemini_browser import generate_prompt as gemini_gen
            result = gemini_gen({"raw_prompt": prompt})
            if result:
                log.info("  ✓ Gemini prompt enhancement succeeded")
                return result
            log.warning("  Gemini returned empty, using original prompt")
        except Exception as e:
            log.warning(f"  Gemini prompt enhancement failed: {e}, using original prompt")
    return prompt


# ── Backend script paths ─────────────────────────────────────
VEO3_BROWSER_SCRIPT   = BASE_DIR / "veo3_browser.py"
KLING_BROWSER_SCRIPT  = BASE_DIR / "kling_browser.py"
OIIOII_BROWSER_SCRIPT = BASE_DIR / "oiioii_browser.py"
HF_WAN2_SCRIPT        = BASE_DIR / "huggingface_wan2.py"

# ── Logging ──────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w",
                 encoding="utf-8", errors="replace", closefd=False)
        ),
    ],
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Quota check
# ══════════════════════════════════════════════════════════════

def check_quota(count: int) -> None:
    """Display Veo3 quota. Does not block the fallback chain."""
    log.info(status_str())
    vl = videos_left()
    if vl < count:
        log.warning(
            f"Veo3 quota low ({vl} left, target {count})"
            " — will fall through to Kling / OiiOii / HuggingFace"
        )


# ══════════════════════════════════════════════════════════════
# Backend implementations
# ══════════════════════════════════════════════════════════════

def _run_browser_script(script: Path, prompt: str, output_path: Path,
                        label: str, timeout: int = 360) -> bool:
    """Generic helper: call a browser-based video generation script via subprocess."""
    if not script.exists():
        log.error(f"{script.name} not found: {script}")
        return False

    log.info(f"{label} | prompt={prompt[:60]}...")
    try:
        result = subprocess.run(
            [sys.executable, str(script),
             "--prompt", prompt,
             "--output", str(output_path)],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log.error(f"  {label} timed out ({timeout}s)")
        return False
    except Exception as e:
        log.error(f"  {label} failed: {e}")
        return False

    tag = label.lower()
    for line in (result.stdout or "").strip().splitlines():
        log.info(f"  [{tag}] {line}")
    for line in (result.stderr or "").strip().splitlines():
        log.warning(f"  [{tag}] {line}")

    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 200_000:
        log.info(f"  ✓ {label} success ({output_path.stat().st_size // 1024} KB)")
        return True

    log.warning(f"  {label} failed (returncode={result.returncode}), trying next backend...")
    return False


def _generate_veo3(prompt: str, output_path: Path) -> bool:
    """Google Flow / Veo3 — browser automation, 1000 pts/month."""
    return _run_browser_script(
        VEO3_BROWSER_SCRIPT, prompt, output_path,
        label="Veo3", timeout=600,
    )


def _generate_kling(prompt: str, output_path: Path) -> bool:
    """Kling AI — klingai.com, ~66 credits/day, watermark."""
    return _run_browser_script(
        KLING_BROWSER_SCRIPT, prompt, output_path,
        label="Kling", timeout=600,
    )


def _generate_oiioii(prompt: str, output_path: Path) -> bool:
    """OiiOii — Seedance 2.0 Pro, STAR tokens required."""
    return _run_browser_script(
        OIIOII_BROWSER_SCRIPT, prompt, output_path,
        label="OiiOii", timeout=360,
    )


def _generate_huggingface(prompt: str, output_path: Path) -> bool:
    """HuggingFace Wan2.1 — fully free, no watermark, queue wait ~8-12 min."""
    return _run_browser_script(
        HF_WAN2_SCRIPT, prompt, output_path,
        label="HuggingFace", timeout=1500,
    )


def generate_video(prompt: str, output_path: Path,
                   hf_prompt: str | None = None) -> tuple:
    """
    Run the fallback chain. Returns (success: bool, backend: str | None).

    Chain order:
      Veo3 → Kling → OiiOii → HuggingFace Wan2.1

    Only Veo3 consumes AI Studio quota points.
    hf_prompt: optional alternate prompt for HuggingFace (e.g. Chinese for Wan2.x).
    """
    # 1. Veo3 (primary)
    if _generate_veo3(prompt, output_path):
        return True, "veo3"

    # 2. Kling AI — uncomment to enable
    # log.warning("Veo3 failed, trying Kling AI...")
    # if _generate_kling(prompt, output_path):
    #     return True, "kling"

    # 3. OiiOii — uncomment to enable
    # log.warning("Kling failed, trying OiiOii...")
    # if _generate_oiioii(prompt, output_path):
    #     return True, "oiioii"

    # 4. HuggingFace Wan2.1 (final fallback, always free)
    log.warning("Veo3 failed, falling back to HuggingFace Wan2.1...")
    final_prompt = hf_prompt or prompt
    if hf_prompt:
        log.info(f"  HF prompt: {final_prompt[:60]}...")
    if _generate_huggingface(final_prompt, output_path):
        return True, "huggingface"

    return False, None


# ══════════════════════════════════════════════════════════════
# Parallel mode helpers
# ══════════════════════════════════════════════════════════════

BACKEND_LABELS = {
    "veo3":        "Veo3 (Google Flow, no watermark)",
    "kling":       "Kling AI (klingai.com, watermark)",
    "oiioii":      "OiiOii (Seedance 2.0 Pro)",
    "huggingface": "HuggingFace Wan2.1 (free, no watermark)",
}


def _generate_one_parallel(job: dict) -> dict:
    """Parallel worker: generate one video directly via HuggingFace."""
    prompt = job.get("hf_prompt") or job["prompt"]
    log.info(f"  [parallel {job['idx']}] HF Wan2.1 | {prompt[:50]}...")
    ok = _generate_huggingface(prompt, job["clip_path"])
    return {**job, "ok": ok, "backend": "huggingface" if ok else None}


def generate_videos_parallel(jobs: list[dict]) -> list[dict]:
    """
    Generate N videos simultaneously via HuggingFace Wan2.1.
    3 serial ≈ 36 min; parallel ≈ 12 min (~66% faster).
    """
    log.info(f"Parallel mode: launching {len(jobs)} HuggingFace tasks simultaneously...")
    results = [None] * len(jobs)
    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        future_to_idx = {
            executor.submit(_generate_one_parallel, job): i
            for i, job in enumerate(jobs)
        }
        for future in as_completed(future_to_idx):
            i = future_to_idx[future]
            try:
                results[i] = future.result()
            except Exception as e:
                log.error(f"  Parallel task {jobs[i]['idx']} exception: {e}")
                results[i] = {**jobs[i], "ok": False, "backend": None}
    return results


# ══════════════════════════════════════════════════════════════
# Pipeline
# ══════════════════════════════════════════════════════════════

def _build_job(idx: int, prompt: str, today: datetime.datetime) -> dict:
    """Build a single video job descriptor."""
    today_str = today.strftime("%Y-%m-%d")
    ts        = today.strftime("%H%M%S")
    clip_path = CLIPS_DIR / f"video_{today_str}_{idx}_{ts}.mp4"
    final_prompt = _enhance_prompt(prompt)

    log.info(f"\n── Video {idx} ──")
    log.info(f"  Prompt : {final_prompt[:80]}...")
    log.info(f"  Output : {clip_path.name}")

    return {
        "idx":       idx,
        "prompt":    final_prompt,
        "hf_prompt": final_prompt,
        "clip_path": clip_path,
    }


def _finalize_job(job: dict, ok: bool, backend: str | None) -> dict:
    """Log result and record Veo3 quota if applicable."""
    idx       = job["idx"]
    clip_path = job["clip_path"]

    if not ok:
        log.error(f"Video {idx}: all backends failed")
        return {"idx": idx, "status": "FAILED", "file": None, "backend": None}

    if backend == "veo3":
        remaining = record(videos=1)
        log.info(f"  Veo3 quota recorded — remaining: {remaining}pts ({remaining // 20} videos)")
    else:
        log.info(f"  Generated via {BACKEND_LABELS.get(backend, backend)} (no Veo3 quota used)")

    log.info(f"  ✓ Video {idx} → {clip_path}")
    return {"idx": idx, "status": "DONE", "file": str(clip_path), "backend": backend}


def run(prompt: str, count: int = 1, parallel: bool = False):
    today     = datetime.datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    mode_tag  = "parallel" if (parallel and count > 1) else "serial"

    log.info("=" * 60)
    log.info(f"AI Video Generation | {today_str} | count={count} | mode={mode_tag}")
    log.info("=" * 60)

    check_quota(count)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    results = []

    if parallel and count > 1:
        jobs = [_build_job(i, prompt, today) for i in range(1, count + 1)]
        for jr in generate_videos_parallel(jobs):
            results.append(_finalize_job(jr, jr["ok"], jr["backend"]))
    else:
        for i in range(1, count + 1):
            job = _build_job(i, prompt, today)
            ok, backend = generate_video(job["prompt"], job["clip_path"],
                                         hf_prompt=job.get("hf_prompt"))
            results.append(_finalize_job(job, ok, backend))
            if i < count:
                time.sleep(3)

    log.info("\n" + "=" * 60)
    for r in results:
        icon    = "✓" if r["status"] == "DONE" else "✗"
        backend = BACKEND_LABELS.get(r.get("backend"), r.get("backend") or "—")
        log.info(f"  {icon} [{r['idx']}] {r['status']} via {backend}")
        if r.get("file"):
            log.info(f"       {r['file']}")
    log.info("=" * 60 + "\n")

    return results


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AI Video Generation Pipeline — multi-backend fallback chain",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main_smartcat.py --prompt "A cat chasing a laser dot, cinematic slow motion"
  python main_smartcat.py --prompt "..." --count 3
  python main_smartcat.py --prompt "..." --count 3 --parallel
  python main_smartcat.py --recover
        """,
    )
    parser.add_argument("--prompt",    type=str, default="",
                        help="Video generation prompt (required unless --recover)")
    parser.add_argument("--count",     type=int, default=1,
                        help="Number of videos to generate (default: 1)")
    parser.add_argument("--parallel",  action="store_true",
                        help="Parallel mode: all N videos via HuggingFace simultaneously "
                             "(requires --count 2+, ~3x faster)")
    parser.add_argument("--recover",   action="store_true",
                        help="Scan Flow + clips folder to recover unprocessed videos")
    parser.add_argument("--scan-only", action="store_true",
                        help="With --recover: report only, no actions taken")
    parser.add_argument("--no-flow",   action="store_true",
                        help="With --recover: skip Google Flow scan")
    args = parser.parse_args()

    if args.recover:
        from recovery import recover_all
        recover_all(scan_only=args.scan_only, no_flow=args.no_flow)
    else:
        if not args.prompt:
            parser.error("--prompt is required (or use --recover)")
        run(prompt=args.prompt, count=args.count, parallel=args.parallel)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  