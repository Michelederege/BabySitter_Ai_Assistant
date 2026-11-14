"""Small requests answered on this PC without the language model."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QuickCommand:
    kind: str
    speech: str = ""
    detail: str = ""
    seconds: int = 0


def match_quick_command(text: str) -> QuickCommand | None:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    phrase = " ".join(words)
    if not phrase:
        return None
    if phrase in {"undo", "cancel that", "cancel the timer"}:
        return QuickCommand("undo", "Okay.")
    if phrase in {"why did you say that", "why did you say that?"}:
        return QuickCommand("why")
    if phrase in {
        "what time is it",
        "whats the time",
        "what is the time",
        "what's the time",
    }:
        return QuickCommand("time")
    if phrase in {
        "whats my vram",
        "what's my vram",
        "what is my vram",
        "video memory",
        "how much video memory",
    } or "vram" in words:
        return QuickCommand("vram")
    if phrase in {
        "hows my pc",
        "how's my pc",
        "how is my pc",
        "pc health",
        "how is my computer",
    }:
        return QuickCommand("health")
    if phrase in {
        "look at my screen",
        "look at the screen",
        "whats on my screen",
        "what's on my screen",
        "what is on my screen",
    }:
        return QuickCommand("screen")
    timer = _timer_seconds(phrase)
    if timer:
        return QuickCommand("timer", seconds=timer)
    return None


def _timer_seconds(phrase: str) -> int:
    match = re.search(r"timer(?: for)? (\d+) (second|seconds|minute|minutes|hour|hours)", phrase)
    if not match:
        return 0
    count = int(match.group(1))
    unit = match.group(2)
    if unit.startswith("hour"):
        seconds = count * 3600
    elif unit.startswith("minute"):
        seconds = count * 60
    else:
        seconds = count
    if seconds < 1 or seconds > 24 * 3600:
        return 0
    return seconds


def timer_label(seconds: int) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
    return f"{seconds} second" if seconds == 1 else f"{seconds} seconds"
