"""Small requests answered on this PC without the language model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class QuickCommand:
    kind: str
    speech: str = ""
    detail: str = ""
    seconds: int = 0
    when: str = ""


_LEAD = re.compile(
    r"^(?:baby\s*sitter|please|can you|could you|would you)\b[\s,]*",
    re.IGNORECASE,
)
_TRAIL = re.compile(r"[\s,]*(?:please|thanks|thank you)\s*$", re.IGNORECASE)


def strip_lead(text: str) -> str:
    """Drop a leading keyword or 'please', and a trailing 'please'.

    The words that were asked for stay, including their capital letters.
    """
    raw = (text or "").strip()
    previous = None
    while raw and previous != raw:
        previous = raw
        raw = _LEAD.sub("", raw, count=1).strip()
    return _TRAIL.sub("", raw).strip()


def _tail(original: str, label: str) -> str:
    match = re.search(rf"\b{re.escape(label)}\b\s*(.*)$", original, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).strip(" .,")


def match_quick_command(text: str) -> QuickCommand | None:
    original = strip_lead(text)
    words = re.findall(r"[a-z0-9']+", original.lower())
    phrase = " ".join(words)
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
        "tell me the time",
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
        "how is my computer doing",
        "hows my computer doing",
        "how's my computer doing",
        "how is the computer",
        "hows the computer",
        "how's the computer",
        "pc health",
    }:
        return QuickCommand("health")
    if phrase in {
        "look at my screen",
        "look at the screen",
        "whats on my screen",
        "what's on my screen",
        "what is on my screen",
        "whats on the screen",
        "what's on the screen",
        "what is on the screen",
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
    journal = _journal_command(phrase, original)
    if journal:
        return journal
    search = _search_command(phrase, original)
    if search:
        return search
    if phrase.startswith("remember "):
        detail = _tail(original, "remember")
        if detail:
            return QuickCommand("remember", detail=detail)
    if phrase in {
        "read my history",
        "read out my history",
        "read the history",
        "read out the history",
        "read my conversation",
        "read out my conversation",
        "what did we talk about",
    }:
        return QuickCommand("history")
    reminder = _reminder(phrase, original)
    if reminder:
        return reminder
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


def _journal_command(phrase: str, original: str) -> QuickCommand | None:
    if phrase in {
        "what did i do today",
        "what have i done today",
        "what did i work on today",
        "show my day",
        "my day",
        "todays journal",
        "today's journal",
    }:
        return QuickCommand("journal_today")
    if phrase in {
        "what did i do yesterday",
        "what did i work on yesterday",
        "yesterdays journal",
        "yesterday's journal",
    }:
        return QuickCommand("journal_yesterday")
    for label in ("start task", "start a task", "new task", "start working on"):
        if phrase.startswith(label + " "):
            detail = _tail(original, label.split()[-1])
            if detail:
                return QuickCommand("task_start", detail=detail)
    if phrase in {
        "done",
        "im done",
        "i'm done",
        "task done",
        "done with that",
        "finish task",
        "finish the task",
        "finished the task",
    }:
        return QuickCommand("task_done")
    if phrase in {"pause the journal", "stop the journal", "journal off"}:
        return QuickCommand("journal_pause")
    if phrase in {"resume the journal", "start the journal", "journal on"}:
        return QuickCommand("journal_resume")
    return None


def _search_command(phrase: str, original: str) -> QuickCommand | None:
    number = re.fullmatch(r"open (?:number |file )?(\d{1,2})", phrase)
    if number:
        return QuickCommand("open_number", seconds=int(number.group(1)))
    for label in ("find", "pull up", "look for", "locate"):
        if phrase == label or not phrase.startswith(label + " "):
            continue
        detail = _tail(original, label.split()[-1])
        if not detail:
            return None
        # "find out about ..." and "look for news ..." belong to the model.
        first = detail.split()[0].lower() if detail.split() else ""
        if first in {"out", "news", "information", "info"}:
            return None
        return QuickCommand("find", detail=detail)
    return None


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


_HOUR_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_MINUTE_WORDS = {
    "five": 5,
    "ten": 10,
    "fifteen": 15,
    "twenty": 20,
    "twenty five": 25,
    "thirty": 30,
    "forty": 40,
    "forty five": 45,
    "forty-five": 45,
    "fifty": 50,
    "fifty five": 55,
    "half": 30,
    "quarter": 15,
}
_REMINDER_LABELS = (
    "set a reminder",
    "set reminder",
    "add a reminder",
    "add reminder",
    "make a reminder",
    "remind me",
)


def _reminder(phrase: str, original: str) -> QuickCommand | None:
    for label in _REMINDER_LABELS:
        if phrase != label and not phrase.startswith(label + " "):
            continue
        detail = _tail(original, label)
        if not detail:
            return None
        moment = clock_in(detail, datetime.now().astimezone())
        when = moment.isoformat(timespec="minutes") if moment else ""
        if moment is not None:
            detail = _without_clock(detail) or detail
        return QuickCommand("remind", detail=detail, when=when)
    return None


def clock_in(text: str, now: datetime) -> datetime | None:
    """The next time this sentence names. None when it names no clock time."""
    lowered = (text or "").lower().replace("a.m.", "am").replace("p.m.", "pm")
    lowered = lowered.replace("a.m", "am").replace("p.m", "pm")
    numbered = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lowered)
    if numbered:
        return _next_clock(int(numbered.group(1)), int(numbered.group(2) or 0), numbered.group(3), now)
    spoken = re.search(
        r"\bat\s+(midnight|noon|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
        r"(?:\s+(o'clock|oclock|five|ten|fifteen|twenty five|twenty|thirty|forty five|forty-five|forty|fifty five|fifty|half|quarter))?"
        r"(?:\s+(am|pm))?",
        lowered,
    )
    if not spoken:
        return None
    word = spoken.group(1)
    if word == "midnight":
        return _next_clock(0, 0, "am", now)
    if word == "noon":
        return _next_clock(12, 0, "pm", now)
    minute_word = spoken.group(2) or ""
    minute = 0 if minute_word in {"", "o'clock", "oclock"} else _MINUTE_WORDS[minute_word]
    return _next_clock(_HOUR_WORDS[word], minute, spoken.group(3), now)


def _next_clock(hour: int, minute: int, ampm: str | None, now: datetime) -> datetime | None:
    if minute < 0 or minute > 59 or hour < 0 or hour > 23:
        return None
    if ampm:
        if hour == 0 or hour > 12:
            return None
        chosen = 0 if hour == 12 and ampm == "am" else hour % 12
        if ampm == "pm" and chosen != 12:
            chosen += 12
        if hour == 12 and ampm == "pm":
            chosen = 12
        hours = [chosen]
    elif hour > 12:
        hours = [hour]
    elif hour == 0:
        hours = [0]
    elif hour == 12:
        hours = [0, 12]
    else:
        hours = [hour, hour + 12]
    best: datetime | None = None
    zone = now.tzinfo
    for extra in (0, 1):
        day = (now + timedelta(days=extra)).date()
        for chosen_hour in hours:
            candidate = datetime(day.year, day.month, day.day, chosen_hour, minute, tzinfo=zone)
            if candidate <= now:
                continue
            if best is None or candidate < best:
                best = candidate
    return best


def _without_clock(detail: str) -> str:
    cleaned = re.sub(
        r"\bat\s+.+?(?=\s+to\b|\s+about\b|\s+that\b|$)",
        " ",
        detail,
        count=1,
        flags=re.IGNORECASE,
    )
    return " ".join(cleaned.split()).strip(" .,")


def spoken_clock(moment: datetime) -> str:
    return moment.strftime("%I:%M %p").lstrip("0")


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
