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
    if phrase.startswith("babysitter "):
        phrase = phrase[len("babysitter ") :].strip()
        words = phrase.split()
    elif phrase.startswith("baby sitter "):
        phrase = phrase[len("baby sitter ") :].strip()
        words = phrase.split()
    if not phrase:
        return None
    if phrase in {"undo", "cancel that", "cancel the timer"}:
        return QuickCommand("undo", "Okay.")
    if phrase in {"why did you say that", "why did you say that?"}:
        return QuickCommand("why")
    if phrase in {"weekly review", "review my week"}:
        return QuickCommand("weekly")
    rating = _rating(phrase)
    if rating:
        return QuickCommand("rate", detail=rating)
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
        "hows my computer",
        "how's my computer",
        "how is my computer",
        "pc health",
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
    if phrase in {
        "read the small text",
        "read the small text on my screen",
        "read the small text on the screen",
    }:
        return QuickCommand("screen_text")
    if _wants_pc_scan(phrase):
        return QuickCommand("scan")
    if phrase in {
        "check my email",
        "check my mail",
        "any new email",
        "any new emails",
        "any new mail",
        "read my email",
        "check email",
    }:
        return QuickCommand("mail")
    if phrase in {
        "check my calendar",
        "whats on my calendar",
        "what's on my calendar",
        "what is on my calendar",
        "any meetings",
        "check calendar",
    }:
        return QuickCommand("calendar")
    if phrase.startswith("remember "):
        detail = phrase[len("remember ") :].strip()
        if detail:
            return QuickCommand("remember", detail=detail)
    if phrase.startswith("remind me"):
        detail = phrase[len("remind me") :].strip()
        if detail:
            return QuickCommand("remind", detail=detail)
    timer = _timer_seconds(phrase)
    if timer:
        return QuickCommand("timer", seconds=timer)
    return None


_SCAN_PHRASES = (
    "scan my pc",
    "scan my computer",
    "scan this pc",
    "scan this computer",
    "scan the pc",
    "scan the computer",
    "scan my hardware",
    "scan my ram",
    "scan my memory",
    "hardware scan",
    "optimize my pc",
    "optimize my computer",
    "optimize this pc",
    "optimize this computer",
    "how can i optimize",
)


_PRESSURE = {"high", "usage", "using", "used", "slow", "full", "check", "scan", "heavy", "eating", "hogging", "free"}


def _wants_pc_scan(phrase: str) -> bool:
    """True when the sentence is asking this PC to look at itself.

    The heard line from a real session was "i'd like you to scan my computer
    my ram usage is very high." That has to scan here. So does "why is my ram
    so high" and "my computer is slow." A web search, a reminder, and a story
    about a memory do not.
    """
    if phrase.startswith(("search ", "remember ", "remind me")):
        return False
    if "ram is in the" in phrase or "memory of" in phrase or "memory from" in phrase:
        return False
    if any(part in phrase for part in _SCAN_PHRASES):
        return True
    words = set(phrase.split())
    if "ram" in words and (words & _PRESSURE or "too much" in phrase):
        return True
    if "memory" in words and (words & _PRESSURE or "too much" in phrase):
        return True
    if "clean up" in phrase and words & {"pc", "computer", "memory", "ram", "hardware"}:
        return True
    machine = bool(words & {"pc", "computer", "hardware"})
    return machine and bool(words & {"scan", "optimize", "slow", "cleanup", "check", "lagging", "laggy", "freezing", "frozen"})


def _rating(phrase: str) -> str:
    table = {
        "rate that shorter": "shorter",
        "too long": "shorter",
        "rate that longer": "longer",
        "too short": "longer",
        "rate that warmer": "warmer",
        "too cold": "warmer",
        "rate that cooler": "cooler",
        "too warm": "cooler",
        "rate that just right": "just right",
        "that was just right": "just right",
    }
    return table.get(phrase, "")


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
