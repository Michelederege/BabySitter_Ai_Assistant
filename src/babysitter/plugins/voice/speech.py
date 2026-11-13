"""Turn a reply into something that can be spoken.

The screen can keep the full answer. The voice gets a short, plain sentence.
Symbols and code fences are left out so they are not read aloud.
"""

from __future__ import annotations

import re


def for_speech(text: str) -> str:
    """Drop markdown and code fences. The words stay."""
    kept: list[str] = []
    skipping_code = False
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            skipping_code = not skipping_code
            continue
        if skipping_code:
            continue
        cleaned = re.sub(r"[*_#`>|]+", "", line)
        cleaned = re.sub(r"\[(.*?)\]\([^)]*\)", r"\1", cleaned)
        cleaned = cleaned.strip()
        if cleaned:
            kept.append(cleaned)
    spoken = " ".join(kept)
    spoken = re.sub(r"\s+", " ", spoken).strip()
    return spoken[:400]


def first_sentence(text: str) -> str:
    spoken = for_speech(text)
    if not spoken:
        return ""
    for mark in (". ", "? ", "! "):
        index = spoken.find(mark)
        if index != -1:
            return spoken[: index + 1]
    if spoken[-1] not in ".!?":
        return spoken + "."
    return spoken


def sapi_rate(speed_percent: int) -> int:
    """Map the speed slider (80–130) onto the Windows voice rate (−10 to 10)."""
    try:
        speed = int(speed_percent)
    except (TypeError, ValueError):
        speed = 100
    return max(-10, min(10, round((speed - 100) / 5)))
