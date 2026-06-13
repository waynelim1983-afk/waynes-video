"""
Veo 3 monthly quota tracker
  - 1000 points / month
  - 20 points per video (9:16, 1x, veo-3.1-fast)
  - Resets on the 9th of each month
"""
import json
from datetime import datetime
from pathlib import Path

QUOTA_FILE   = Path(r"C:\projects\YT\amazon\logs\quota.json")
MONTHLY_QUOTA   = 1940   # Flow 点數(1000) + AI 备用点數(940)，实际剩余以 Google Flow UI 为准
COST_PER_VIDEO  = 20
RESET_DAY       = 9


def _period() -> str:
    """Return YYYY-MM for the current billing period (resets on 9th)."""
    now = datetime.now()
    if now.day < RESET_DAY:
        m = now.month - 1 or 12
        y = now.year if now.month > 1 else now.year - 1
        return f"{y}-{m:02d}"
    return f"{now.year}-{now.month:02d}"


def _load() -> dict:
    return json.loads(QUOTA_FILE.read_text("utf-8")) if QUOTA_FILE.exists() else {}


def _save(data: dict):
    QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUOTA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")


def used() -> int:
    return _load().get(_period(), {}).get("used", 0)


def remaining() -> int:
    return MONTHLY_QUOTA - used()


def videos_left() -> int:
    return remaining() // COST_PER_VIDEO


def can_generate() -> bool:
    return remaining() >= COST_PER_VIDEO


def record(videos: int = 1) -> int:
    """Record video generation usage. Returns remaining points."""
    data = _load()
    p    = _period()
    entry = data.setdefault(p, {"used": 0, "videos": 0})
    entry["used"]    += COST_PER_VIDEO * videos
    entry["videos"]  += videos
    entry["updated"]  = datetime.now().isoformat()
    _save(data)
    return remaining()


def next_reset() -> str:
    now = datetime.now()
    if now.day < RESET_DAY:
        return f"{now.year}-{now.month:02d}-{RESET_DAY:02d}"
    m = now.month + 1 if now.month < 12 else 1
    y = now.year if now.month < 12 else now.year + 1
    return f"{y}-{m:02d}-{RESET_DAY:02d}"


def status_str() -> str:
    return (
        f"Veo3 配額 | 本期已用: {used()}pts | "
        f"剩餘: {remaining()}pts ({videos_left()} 支影片) | "
        f"下次重置: {next_reset()}"
    )


if __name__ == "__main__":
    print(status_str())
