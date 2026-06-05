"""
prompt_validator.py — 跨平台 prompt 品質檢查與清理

validate_prompt(platform, prompt) -> cleaned_prompt
"""

import re
import logging

log = logging.getLogger(__name__)

_FILLER_PATTERN = re.compile(
    r"\b(?:beautiful|masterpiece|detailed|high[\s\-]quality|cinematic|8k|4k|ultra[\s\-]HD)\b",
    flags=re.IGNORECASE,
)

_SEEDANCE_TAIL = (
    "no deformation, no drift, no artifacts, "
    "locked horizon, smooth motion, temporal consistency"
)


def validate_prompt(platform: str, prompt: str) -> str:
    """
    清理 prompt 並依平台規則發出 WARNING。
    回傳清理後的 prompt（已補 tail / 替換關鍵詞等）。
    """
    # ── 全平台：移除廢詞
    cleaned = _FILLER_PATTERN.sub("", prompt)
    cleaned = re.sub(r"  +", " ", cleaned).strip()

    plat = platform.lower()

    # ── Kling
    if plat == "kling":
        words = cleaned.split()
        if len(words) > 80:
            log.warning(f"[validator][kling] prompt 超過 80 字（{len(words)} 字），Kling 效果可能下降")

        subjects = re.findall(r"\b(?:a|an|the)\s+\w+", cleaned, flags=re.IGNORECASE)
        if len(subjects) > 5:
            log.warning(
                f"[validator][kling] 主體名詞數量超過 5 個（{len(subjects)} 個），可能導致 Kling 混亂"
            )

        stacked = re.search(
            r"\b(zoom\s+(?:in|out)|pan(?:ning)?|tilt(?:ing)?|dolly|truck(?:ing)?)\b"
            r".{0,30}"
            r"\b(zoom(?:ing)?|pan(?:ning)?|tilt(?:ing)?|dolly|truck(?:ing)?)\b",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if stacked:
            log.warning(f"[validator][kling] 堆疊運鏡偵測：「{stacked.group()[:60]}」，Kling 可能無法執行")

    # ── OiiOii / Seedance
    elif plat in ("oiioii", "seedance"):
        if re.search(r"\bfast\b", cleaned, flags=re.IGNORECASE):
            cleaned = re.sub(r"\bfast\b", "extreme speed", cleaned, flags=re.IGNORECASE)
            log.warning("[validator][oiioii] 'fast' → 'extreme speed'（Seedance 的 fast 會爛）")

        verbs = re.findall(
            r"\b(?:runs|walks|jumps|spins|turns|moves|flies|swims|dances|climbs|"
            r"crawls|slides|rolls|bounces|shakes|waves|nods|looks|gazes|stares|"
            r"watches|approaches|retreats|advances|backs|paws|licks|drinks)\b",
            cleaned,
            flags=re.IGNORECASE,
        )
        if len(verbs) >= 3:
            log.warning(f"[validator][oiioii] 多動詞疊加偵測（{verbs}），主體可能動作混亂")

        if "no deformation" not in cleaned.lower() and "temporal consistency" not in cleaned.lower():
            cleaned = cleaned.rstrip(". ") + ". " + _SEEDANCE_TAIL
            log.info("[validator][oiioii] 已補上 constraints tail")

    # ── Veo
    elif plat == "veo":
        if not re.search(r"\b(SFX:|Soundtrack:|sound)\b", cleaned, flags=re.IGNORECASE):
            log.warning("[validator][veo] 缺少音訊描述（SFX: / Soundtrack: / sound）")

        wc = len(cleaned.split())
        if wc < 80:
            log.warning(f"[validator][veo] prompt 過短（{wc} 字，建議 80~200 字）")
        elif wc > 200:
            log.warning(f"[validator][veo] prompt 過長（{wc} 字，建議 80~200 字）")

    return cleaned
