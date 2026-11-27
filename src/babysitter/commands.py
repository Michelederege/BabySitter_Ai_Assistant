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
    r"^(?:hey|okay|ok|baby\s*sitter|please|can you|could you|would you)\b[\s,]*",
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
    found = _match_quick_command(text)
    if found is not None:
        return found
    alt = loosen_heard(text)
    if not alt:
        return None
    return _match_quick_command(alt)


def loosen_heard(text: str) -> str:
    """A misheard command head, only when the words are a known slip.

    The rest of the line stays as it was heard. A line that is already a
    command is not rewritten. Callers try the original first.
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    for source, dest in (
        ("set a time for", "set a timer for"),
        ("set a time or", "set a timer for"),
        ("rewind me", "remind me"),
        ("reminded me", "remind me"),
        ("say that back", "say that again"),
    ):
        if lowered.startswith(source):
            return dest + raw[len(source):]
    words = raw.split()
    if not words:
        return ""
    head = words[0].lower().strip(".,")
    if head == "fine" and any(token in lowered for token in ("pdf", "file", "files", "doc", "docx", "txt")):
        return "find " + " ".join(words[1:])
    if head in {"rewind", "reminded"}:
        return "remind " + " ".join(words[1:])
    return ""


# More of the ordinary ways people say the same thing. Each maps to a phrase
# the tables below already know, so a new wording never needs a new handler.
_SAME_AS = {
    "do you know what time it is": "what time is it",
    "what time is it now": "what time is it",
    "whats the time now": "what time is it",
    "what's the time now": "what time is it",
    "time please": "what time is it",
    "time": "what time is it",
    "the time": "what time is it",
    "current time": "what time is it",
    "got the time": "what time is it",
    "whats the date today": "what is the date",
    "what's the date today": "what is the date",
    "what is the date today": "what is the date",
    "what day is today": "what day is it",
    "what day is it today": "what day is it",
    "whats today": "what day is it",
    "what's today": "what day is it",
    "stop the timer": "cancel the timer",
    "stop timer": "cancel the timer",
    "kill the timer": "cancel the timer",
    "cancel my timer": "cancel the timer",
    "cancel timer": "cancel the timer",
    "undo that": "undo",
    "undo it": "undo",
    "end the timer": "cancel the timer",
    "how long is left on the timer": "what's my next reminder",
    "how much time is left": "what's my next reminder",
    "how much time is left on the timer": "what's my next reminder",
    "how long is left": "what's my next reminder",
    "how much longer": "what's my next reminder",
    "whats left on the timer": "what's my next reminder",
    "what's left on the timer": "what's my next reminder",
    "read my emails": "read my email",
    "read me my emails": "read my email",
    "check my emails": "check my email",
    "any emails": "any new email",
    "did i get any email": "any new email",
    "did i get any emails": "any new email",
    "whats in my inbox": "check my inbox",
    "what's in my inbox": "check my inbox",
    "what do i have today": "check my calendar",
    "whats my schedule": "check my calendar",
    "what's my schedule": "check my calendar",
    "what is my schedule": "check my calendar",
    "whats on today": "check my calendar",
    "what's on today": "check my calendar",
    "whats on my schedule": "check my calendar",
    "what's on my schedule": "check my calendar",
    "do i have anything today": "check my calendar",
    "am i busy today": "check my calendar",
}
_COUNTDOWN = re.compile(
    r"(?:(?:set|start|make|put on|give me)\s+)?(?:a|an|me a)?\s*([a-z0-9]+(?:\s+and\s+a\s+half)?)\s*"
    r"(second|seconds|minute|minutes|min|mins|hour|hours)\s+timer(?:\s+(?:for|to)\s+(.+))?"
)
_TIMER_ON = re.compile(r"(?:put|set|start)\s+(?:a\s+)?timer\s+on\s+for\s+(.+)")


def _same_as(phrase: str) -> str:
    """The wording the tables know, for a few common other ways of saying it."""
    if phrase in _SAME_AS:
        return _SAME_AS[phrase]
    countdown = _COUNTDOWN.fullmatch(phrase)
    if countdown:
        amount, unit, purpose = countdown.group(1), countdown.group(2), countdown.group(3)
        unit = {"min": "minutes", "mins": "minutes"}.get(unit, unit)
        rebuilt = f"set a timer for {amount} {unit}"
        return rebuilt + (f" to {purpose}" if purpose else "")
    timer_on = _TIMER_ON.fullmatch(phrase)
    if timer_on:
        return "set a timer for " + timer_on.group(1)
    return phrase


def _match_quick_command(text: str) -> QuickCommand | None:
    original = strip_lead(text)
    words = re.findall(r"[a-z0-9']+", original.lower())
    phrase = " ".join(words)
    if not phrase:
        return None
    if phrase in _MEMORY_QUESTIONS:
        return QuickCommand("memories")
    if phrase in _BRIEFING:
        return QuickCommand("briefing")
    same = _same_as(phrase)
    if same != phrase:
        phrase = same
        original = same
        words = phrase.split()
    if phrase in {"undo", "cancel that"}:
        return QuickCommand("undo", "Okay.")
    if phrase == "cancel the timer":
        # Not "undo": undo only reaches back 10 seconds, and a timer can be
        # stopped at any point before it rings.
        return QuickCommand("cancel_timer")
    if phrase in {"why did you say that", "why did you say that?"}:
        return QuickCommand("why")
    if phrase in {"weekly review", "review my week"}:
        return QuickCommand("weekly")
    rating = _rating(phrase)
    if rating:
        return QuickCommand("rate", detail=rating)
    persona = _persona(phrase)
    if persona is not None:
        return QuickCommand("persona", detail=persona)
    if phrase in _NAME_QUESTIONS:
        return QuickCommand("my_name")
    if phrase in {
        "what time is it",
        "whats the time",
        "what is the time",
        "what's the time",
        "tell me the time",
        "what day is it",
        "what day of the week is it",
        "whats the date",
        "what's the date",
        "what is the date",
        "whats today's date",
        "what's today's date",
        "what is today's date",
        "tell me the date",
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
        "what am i looking at",
        "take a look at my screen",
        "take a look at the screen",
    } or phrase.startswith(("what's on my screen ", "whats on my screen ", "what is on my screen ", "what's on the screen ", "whats on the screen ", "what is on the screen ")):
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
        "any unread mail",
        "any mail",
        "do i have email",
        "do i have any email",
        "check inbox",
        "check my inbox",
    }:
        return QuickCommand("mail")
    if phrase in {
        "check my calendar",
        "whats on my calendar",
        "what's on my calendar",
        "what is on my calendar",
        "any meetings",
        "any meetings today",
        "check calendar",
        "am i free today",
        "do i have meetings today",
        "what meetings do i have",
    }:
        return QuickCommand("calendar")
    journal = _journal_command(phrase, original)
    if journal:
        return journal
    search = _search_command(phrase, original)
    if search:
        return search
    from babysitter.goals import match_goal

    goal = match_goal(text)
    if goal is not None:
        return goal
    if phrase.startswith("remember "):
        detail = _tail(original, "remember")
        if detail:
            return QuickCommand("remember", detail=detail)
    for label in (
        "make a note that",
        "make a note",
        "note that",
        "jot this down",
        "jot down",
        "don't forget that",
        "dont forget that",
    ):
        if phrase.startswith(label + " "):
            detail = _tail(original, label)
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
    extra = _local_extra(phrase, original)
    if extra is not None:
        return extra
    timer = _timer_command(phrase, original)
    if timer:
        return timer
    reminder = _reminder(phrase, original)
    if reminder:
        return reminder
    named = _timer_as_reminder(phrase, original)
    if named:
        return named
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
        "how did my day go",
        "how was my day",
        "hows my day",
        "how's my day",
    }:
        return QuickCommand("journal_today")
    if phrase in {
        "what did i do yesterday",
        "what did i work on yesterday",
        "yesterdays journal",
        "yesterday's journal",
        "how was yesterday",
        "how did yesterday go",
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


_OPEN_WORDS = {
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
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}


def _open_index(phrase: str) -> int | None:
    """'open number 2', 'open number two', and 'open the second one'."""
    match = re.fullmatch(r"open (?:number |file |the )?([a-z0-9]+)(?: one)?", phrase)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        value = int(token)
        return value if 1 <= value <= 99 else None
    return _OPEN_WORDS.get(token)


def _asks_for_goals(detail: str) -> bool:
    """True when the words name the goals list, not a file."""
    words = re.findall(r"[a-z0-9']+", (detail or "").lower())
    return words in (
        ["goal"],
        ["goals"],
        ["my", "goal"],
        ["my", "goals"],
        ["the", "goal"],
        ["the", "goals"],
    )


def _summary_index(phrase: str) -> int | None:
    """'summarize number 2', 'read number two', 'what's in the second one'."""
    match = re.fullmatch(
        r"(?:summarize|summarise|sum up|read|read me|read out|what's in|whats in|what is in|tell me about)"
        r" (?:number |file |the )?([a-z0-9]+)(?: one| file)?",
        phrase,
    )
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        value = int(token)
        return value if 1 <= value <= 99 else None
    return _OPEN_WORDS.get(token)


def _search_command(phrase: str, original: str) -> QuickCommand | None:
    number = _open_index(phrase)
    if number is not None:
        return QuickCommand("open_number", seconds=number)
    number = _summary_index(phrase)
    if number is not None:
        return QuickCommand("summarize_number", seconds=number)
    drive = re.fullmatch(
        r"(?:read|summarize|summarise|sum up|open|what's in|whats in|what is in)"
        r" (?:my |the )?(?:google )?drive (?:file |doc |document )?(?:called |named )?(.{2,80})",
        phrase,
    )
    if drive:
        return QuickCommand("drive_text", detail=drive.group(1).strip())
    heard = phrase.replace("where's", "where is").replace("wheres", "where is")
    for label in ("where is my", "where is the", "show me my"):
        if not heard.startswith(label + " "):
            continue
        detail = _tail(original, label)
        if not detail:
            return None
        from babysitter.filefind import parse_query

        _words, extensions = parse_query(detail)
        tokens = set(re.findall(r"[a-z0-9]+", detail.lower()))
        if extensions or tokens & {"file", "files"}:
            return QuickCommand("find", detail=detail)
        return None
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
        if _asks_for_goals(detail):
            return None
        return QuickCommand("find", detail=detail)
    return None


# "Be quiet" and "be honest" are requests, not names.
_NOT_A_NAME = {
    "quiet", "quick", "quicker", "honest", "careful", "nice", "brief", "short", "shorter",
    "long", "longer", "warm", "warmer", "cool", "cooler", "serious", "funny", "right", "back",
    "ready", "more", "less", "concise", "polite", "kind", "gentle", "direct", "there", "here",
    "done", "a", "an", "the", "my", "it", "that", "this", "clear", "clearer", "specific",
    "precise", "patient", "silent", "still", "calm", "real", "straight", "fast", "faster",
    "slow", "slower", "louder", "softer", "better", "good", "creative", "detailed", "friendly",
    "later", "tomorrow", "soon", "again", "sometime", "tonight", "when", "if", "what", "something",
    "anything", "fine", "okay", "ok", "sure", "nothing", "whatever", "me", "you", "us", "him", "her",
}


# UI v3, Today: the daily briefing. Said on request; it is never pushed at you.
_BRIEFING = {
    "brief me", "daily briefing", "my briefing", "give me my briefing", "morning briefing",
    "good morning", "morning", "what's my day look like", "whats my day look like",
    "what does my day look like", "catch me up", "fill me in", "what's up today", "whats up today",
}

_MEMORY_QUESTIONS = {
    "what do you remember about me", "what do you know about me", "what have you remembered",
    "what have you remembered about me", "what do you remember", "what have i told you",
    "what facts do you have", "what are my saved facts", "list my memories", "read my memories",
}

_NAME_QUESTIONS = {
    "what's your name", "what is your name", "whats your name", "who are you", "what do i call you",
    "what should i call you", "what did i call you", "what's your nickname", "what is your nickname",
    "do you remember your name", "do you remember what i call you", "what are you called",
}

# Every ordinary way of giving it a nickname. One sentence is the whole setup.
_NAMING = (
    r"(?:(?:okay|ok|so|alright|hey)\s+)?(?:from now on\s+)?"
    r"(?:be|become|call yourself|your name is|your name's|be called|your new name is|"
    r"your nickname is|your new nickname is|change your name to|rename yourself(?: to)?|"
    r"(?:i'll|i will|i'm going to|i'm gonna|im going to|im gonna|i want to|i wanna|i'd like to|"
    r"let me|let's|lets|can i|could i|may i|we'll|i shall)\s+call you|"
    r"call you|you're called|you are called|answer to)\s+([a-z' -]{2,40})"
)
# Words that end the sentence but are not part of the name.
_NAME_TAIL = {"please", "now", "okay", "ok", "instead", "from", "on", "then", "thanks", "thank", "you"}


def _persona(phrase: str) -> str | None:
    """A name to answer to, or "" to drop it. None when this is not about a persona."""
    if phrase in {"be yourself", "go back to being yourself", "stop being edith", "drop the persona", "no persona"}:
        return ""
    match = re.fullmatch(_NAMING, phrase)
    if not match:
        return None
    name = match.group(1).strip()
    words = name.split()
    while words and words[-1] in _NAME_TAIL:
        words.pop()
    name = " ".join(words)
    if not 1 <= len(words) <= 2 or words[0] in _NOT_A_NAME:
        return None
    return name


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
    "don't forget to",
    "dont forget to",
)


def _local_extra(phrase: str, original: str) -> QuickCommand | None:
    """Phrases that name one local action and carry no extra words."""
    del original
    if phrase in {
        "check for updates",
        "check for an update",
        "check for update",
        "are there any updates",
        "is there an update",
        "is babysitter up to date",
        "are you up to date",
    }:
        return QuickCommand("check_update")
    if phrase in {
        "update babysitter",
        "update the app",
        "update the application",
        "update the software",
        "update yourself",
        "install the update",
        "install updates",
    }:
        return QuickCommand("apply_update")
    if phrase in {
        "check my drive",
        "whats on my drive",
        "what's on my drive",
        "show my drive",
        "show my google drive",
    }:
        return QuickCommand("drive")
    if phrase in {
        "check my school email",
        "check school email",
        "school email",
        "read my school email",
    }:
        return QuickCommand("school_mail")
    if phrase in {
        "check blackboard",
        "whats on blackboard",
        "what's on blackboard",
        "what is on blackboard",
        "show blackboard",
    }:
        return QuickCommand("blackboard")
    if phrase in {
        "what am i writing",
        "what i'm writing",
        "what am i writing right now",
        "read my draft",
        "read this draft",
        "read my paper",
        "what document am i writing",
    }:
        return QuickCommand("draft")
    if phrase in {
        "what is my next reminder",
        "what's my next reminder",
        "whats my next reminder",
        "when is my next reminder",
        "when's my next reminder",
        "whens my next reminder",
        "next reminder",
        "what reminders do i have",
        "do i have a reminder",
    }:
        return QuickCommand("next_reminder")
    if phrase in {
        "cancel my reminder",
        "cancel the reminder",
        "delete my reminder",
        "delete the reminder",
        "clear my reminder",
        "clear the reminder",
    }:
        return QuickCommand("cancel_reminder")
    if phrase in {
        "say that again",
        "repeat that",
        "repeat the last thing",
        "what did you say",
        "come again",
    }:
        return QuickCommand("repeat")
    if phrase in {
        "stop talking",
        "stop speaking",
        "be quiet",
        "hush",
        "that's enough",
        "thats enough",
    }:
        return QuickCommand("hush")
    if phrase in {"pin that", "pin this", "pin it", "pin the reply"}:
        return QuickCommand("pin")
    return None


_ONES = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
_TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}
_COUNT = {**_ONES, **_TEENS, **_TENS, "zero": 0}
_HOUR_TOKEN = (
    r"midnight|noon|twelve|eleven|ten|nine|eight|seven|six|five|four|three|two|one|\d{1,2}"
)
_MINUTE_TOKEN = (
    r"(?:twenty|thirty|forty|fifty)(?:\s+(?:one|two|three|four|five|six|seven|eight|nine))?"
    r"|nineteen|eighteen|seventeen|sixteen|fifteen|fourteen|thirteen|twelve|eleven|ten"
    r"|nine|eight|seven|six|five|four|three|two|one"
    r"|half|quarter|o'clock|oclock|\d{1,2}"
)
_SHIFT_RE = re.compile(
    rf"\b(?:a\s+)?(quarter|half)\s+(past|after|to|till|til)\s+({_HOUR_TOKEN})(?:\s+(am|pm))?\b"
)
_AT_RE = re.compile(
    rf"\bat\s+({_HOUR_TOKEN})(?:\s+({_MINUTE_TOKEN}))?(?:\s+(am|pm))?\b"
)
_REL_RE = re.compile(
    r"\bin\s+(an?\s+hour\s+and\s+a\s+half|hour\s+and\s+a\s+half|a\s+minute\s+and\s+a\s+half"
    r"|half\s+an?\s+hour|half\s+a\s+minute|an?\s+hour|an?\s+minute|an?\s+second"
    r"|(?:[a-z]+(?:\s+[a-z]+)?|\d+)(?:\s+and\s+a\s+half)?"
    r"\s+(?:seconds|second|minutes|minute|hours|hour))\b"
)
_BARE_AMPM = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)")
_BARE_CLOCK = re.compile(r"(\d{1,2}):(\d{2})")
_DURATION_RE = re.compile(
    r"^(an hour and a half|a hour and a half|hour and a half|a minute and a half"
    r"|half an hour|half a hour|half hour|half a minute|an hour|a hour|a minute|a second)"
    r"|^((?:[a-z]+(?:\s+[a-z]+)?)|\d+)(?:\s+and\s+a\s+half)?"
    r"\s+(seconds|second|minutes|minute|hours|hour)\b"
)


def reminder_fields(text: str, when_text: str, now: datetime) -> tuple[str, str]:
    """The words to keep, and the clock time as text. An empty clock means it will not ring."""
    note = " ".join((text or "").split())
    clock_text = " ".join((when_text or "").split())
    located = _locate_when(clock_text, now) if clock_text else None
    if located is None and note:
        located = _locate_when(note, now)
        if located is not None and not clock_text:
            note = _cut_when(note, located[1]) or "Reminder"
    elif located is not None and not clock_text:
        note = _cut_when(note, located[1]) or "Reminder"
    moment = None if located is None else located[0]
    if not note:
        note = "Reminder"
    due = moment.isoformat(timespec="seconds") if moment else ""
    return note, due


def _reminder(phrase: str, original: str) -> QuickCommand | None:
    for label in _REMINDER_LABELS:
        if phrase != label and not phrase.startswith(label + " "):
            continue
        detail = _tail(original, label)
        if not detail:
            return None
        now = datetime.now().astimezone()
        located = _locate_when(detail, now)
        if located is None:
            return QuickCommand("remind", detail=detail, when="")
        moment, span = located
        detail = _cut_when(detail, span) or "Reminder"
        return QuickCommand("remind", detail=detail, when=moment.isoformat(timespec="seconds"))
    return None


def clock_in(text: str, now: datetime) -> datetime | None:
    """The next time this sentence names. None when it names no clock time."""
    found = _locate_when(text, now, clocks_only=True)
    return None if found is None else found[0]


def _wall_clock(day, hour: int, minute: int, now: datetime) -> datetime:
    """This clock time on that day, with the offset that day really has.

    datetime.now().astimezone() carries today's fixed offset. Reused for
    tomorrow across a daylight-saving change, it put the reminder an hour
    off. A time in this PC's own zone takes that day's offset instead.
    """
    zone = now.tzinfo
    if zone is not None and now.utcoffset() == now.astimezone().utcoffset():
        return datetime(day.year, day.month, day.day, hour, minute).astimezone()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)


def _on_day(now: datetime, days: int, hour: int, minute: int) -> datetime:
    day = (now + timedelta(days=days)).date()
    return _wall_clock(day, hour, minute, now)


def _next_clock(
    hour: int,
    minute: int,
    ampm: str | None,
    now: datetime,
    earliest_day: int = 0,
    *,
    absolute: bool = False,
) -> datetime | None:
    if minute < 0 or minute > 59 or hour < 0 or hour > 23:
        return None
    if absolute:
        hours = [hour]
    elif ampm:
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
        # Bare 12 is noon. Midnight is the word midnight, or 12 am.
        hours = [12]
    else:
        hours = [hour, hour + 12]
    best: datetime | None = None
    for extra in (earliest_day, earliest_day + 1):
        day = (now + timedelta(days=extra)).date()
        for chosen_hour in hours:
            candidate = _wall_clock(day, chosen_hour, minute, now)
            if candidate <= now:
                continue
            if best is None or candidate < best:
                best = candidate
    return best


def _without_clock(detail: str) -> str:
    located = _locate_when(detail, datetime.now().astimezone())
    if located is None:
        cleaned = re.sub(r"\btomorrow\b", " ", detail, flags=re.IGNORECASE)
        return " ".join(cleaned.split()).strip(" .,")
    return _cut_when(detail, located[1])


def _fold_clock(text: str) -> tuple[str, list[int]]:
    """Lower case for matching, and where each folded character sits in the original.

    ``a.m.`` becomes ``am`` and a hyphen becomes a space. The index list maps
    a folded position back onto the note the person actually said.
    """
    raw = text or ""
    lower = raw.lower()
    folded: list[str] = []
    origin: list[int] = []
    index = 0
    while index < len(lower):
        if lower.startswith(("a.m.", "p.m."), index):
            word = "am" if lower[index] == "a" else "pm"
            folded.extend(word)
            origin.extend((index, index))
            index += 4
            continue
        if lower.startswith(("a.m", "p.m"), index):
            word = "am" if lower[index] == "a" else "pm"
            folded.extend(word)
            origin.extend((index, index))
            index += 3
            continue
        folded.append(" " if lower[index] == "-" else lower[index])
        origin.append(index)
        index += 1
    return "".join(folded), origin


def _map_span(origin: list[int], span: tuple[int, int], length: int) -> tuple[int, int]:
    start, end = span
    if not origin or start >= len(origin):
        return length, length
    orig_start = origin[min(start, len(origin) - 1)]
    orig_end = length if end >= len(origin) else origin[end]
    return orig_start, max(orig_start, orig_end)


def _cover_words(folded: str, span: tuple[int, int]) -> tuple[int, int]:
    """Include a leading 'at' and the word tomorrow, so they leave the note."""
    start, end = span
    lead = re.search(r"\bat\s+$", folded[:start])
    if lead:
        start = lead.start()
    word = re.search(r"\btomorrow\b", folded)
    if word:
        start = min(start, word.start())
        end = max(end, word.end())
    return start, end


def _cut_when(detail: str, span: tuple[int, int]) -> str:
    start, end = span
    kept = detail[:start] + " " + detail[end:]
    return " ".join(kept.split()).strip(" .,")


def _count_words(text: str) -> int | None:
    parts = (text or "").split()
    if len(parts) == 1 and parts[0].isdigit():
        return int(parts[0])
    if len(parts) == 1:
        return _COUNT.get(parts[0])
    if len(parts) == 2 and parts[0] in _TENS and parts[1] in _ONES:
        return _TENS[parts[0]] + _ONES[parts[1]]
    return None


def _minute_value(word: str) -> int | None:
    word = (word or "").strip()
    if word in {"", "o'clock", "oclock"}:
        return 0
    if word == "half":
        return 30
    if word == "quarter":
        return 15
    if word in _MINUTE_WORDS and " " not in word and "-" not in word:
        return _MINUTE_WORDS[word]
    value = _count_words(word)
    if value is None or value > 59:
        return None
    return value


def _to_24(hour: int, ampm: str) -> int:
    if hour == 12 and ampm == "am":
        return 0
    if hour == 12 and ampm == "pm":
        return 12
    if ampm == "pm" and hour < 12:
        return hour + 12
    return hour


def _absolute_shift(base: int, delta: int, now: datetime, earliest: int) -> datetime | None:
    total = (base * 60 + delta) % (24 * 60)
    return _next_clock(total // 60, total % 60, None, now, earliest, absolute=True)


def _from_shift(match: re.Match[str], now: datetime, earliest: int) -> datetime | None:
    kind, direction, hour_token, ampm = match.group(1), match.group(2), match.group(3), match.group(4)
    delta = 30 if kind == "half" else 15
    if direction in {"to", "till", "til"}:
        delta = -delta
    if hour_token == "midnight":
        return _absolute_shift(0, delta, now, earliest)
    if hour_token == "noon":
        return _absolute_shift(12, delta, now, earliest)
    hour = int(hour_token) if hour_token.isdigit() else _HOUR_WORDS.get(hour_token)
    if hour is None:
        return None
    if ampm:
        if hour == 0 or hour > 12:
            return None
        return _absolute_shift(_to_24(hour, ampm), delta, now, earliest)
    if hour == 12:
        stayed = 12 * 60 + delta
        if 12 * 60 <= stayed < 13 * 60:
            return _absolute_shift(12, delta, now, earliest)
        best: datetime | None = None
        for base in (0, 12):
            moment = _absolute_shift(base, delta, now, earliest)
            if moment is not None and (best is None or moment < best):
                best = moment
        return best
    if hour > 12:
        return _absolute_shift(hour, delta, now, earliest)
    best = None
    for meridian in ("am", "pm"):
        moment = _absolute_shift(_to_24(hour, meridian), delta, now, earliest)
        if moment is not None and (best is None or moment < best):
            best = moment
    return best


def _from_at(match: re.Match[str], now: datetime, earliest: int) -> datetime | None:
    word = match.group(1)
    minute_word = match.group(2) or ""
    ampm = match.group(3)
    minute = _minute_value(minute_word)
    if minute is None:
        return None
    if word == "midnight":
        return _next_clock(0, minute, "am", now, earliest)
    if word == "noon":
        return _next_clock(12, minute, "pm", now, earliest)
    hour = int(word) if word.isdigit() else _HOUR_WORDS.get(word)
    if hour is None:
        return None
    return _next_clock(hour, minute, ampm, now, earliest)


def _relative_seconds(piece: str) -> int | None:
    text = " ".join((piece or "").split())
    named = {
        "an hour and a half": 90 * 60,
        "a hour and a half": 90 * 60,
        "hour and a half": 90 * 60,
        "a minute and a half": 90,
        "half an hour": 30 * 60,
        "half a hour": 30 * 60,
        "half hour": 30 * 60,
        "half a minute": 30,
        "an hour": 3600,
        "a hour": 3600,
        "a minute": 60,
        "an minute": 60,
        "a second": 1,
        "an second": 1,
    }
    if text in named:
        return named[text]
    match = re.fullmatch(
        r"((?:[a-z]+(?:\s+[a-z]+)?)|\d+)(?:\s+and\s+a\s+half)?\s+(seconds|second|minutes|minute|hours|hour)",
        text,
    )
    if not match:
        return None
    count = _count_words(match.group(1))
    if count is None:
        return None
    unit = match.group(2)
    half = "and a half" in text
    if unit.startswith("hour"):
        seconds = count * 3600 + (1800 if half else 0)
    elif unit.startswith("minute"):
        seconds = count * 60 + (30 if half else 0)
    elif half:
        return None
    else:
        seconds = count
    if seconds < 1 or seconds > 24 * 3600:
        return None
    return seconds


def _locate_when(
    text: str, now: datetime, *, clocks_only: bool = False
) -> tuple[datetime, tuple[int, int]] | None:
    """The moment, and the slice of text that named it."""
    if not (text or "").strip():
        return None
    folded, origin = _fold_clock(text)

    def placed(moment: datetime, span: tuple[int, int]) -> tuple[datetime, tuple[int, int]]:
        return moment, _map_span(origin, _cover_words(folded, span), len(text))

    earliest = 1 if re.search(r"\btomorrow\b", folded) else 0
    colon = re.search(r"\bat\s+(\d{1,2}):(\d{2})\s*(am|pm)?\b", folded)
    if colon:
        moment = _next_clock(
            int(colon.group(1)), int(colon.group(2)), colon.group(3), now, earliest
        )
        if moment is not None:
            return placed(moment, colon.span())
    for pattern, reader in ((_SHIFT_RE, _from_shift), (_AT_RE, _from_at)):
        match = pattern.search(folded)
        if not match:
            continue
        moment = reader(match, now, earliest)
        if moment is None:
            continue
        return placed(moment, match.span())
    if clocks_only:
        return None
    stripped = folded.strip()
    pad = len(folded) - len(folded.lstrip())
    numbered = _BARE_AMPM.fullmatch(stripped)
    if numbered:
        moment = _next_clock(
            int(numbered.group(1)),
            int(numbered.group(2) or 0),
            numbered.group(3),
            now,
            earliest,
        )
        if moment is not None:
            return placed(moment, (pad, pad + len(stripped)))
    hours = _BARE_CLOCK.fullmatch(stripped)
    if hours:
        hour = int(hours.group(1))
        minute = int(hours.group(2))
        if 0 <= hour <= 23:
            moment = _next_clock(hour, minute, None, now, earliest)
            if moment is not None:
                return placed(moment, (pad, pad + len(stripped)))
    if re.fullmatch(r"tomorrow", stripped):
        return placed(_on_day(now, 1, 9, 0), (pad, pad + len(stripped)))
    relative = _REL_RE.search(folded)
    if relative:
        seconds = _relative_seconds(relative.group(1))
        if seconds is not None and not earliest:
            return placed(now + timedelta(seconds=seconds), relative.span())
    if earliest:
        word = re.search(r"\btomorrow\b", folded)
        if word:
            return placed(_on_day(now, 1, 9, 0), word.span())
    return None


def spoken_clock(moment: datetime) -> str:
    return moment.strftime("%I:%M %p").lstrip("0")


def spoken_when(moment: datetime, now: datetime | None = None) -> str:
    """The clock, plus tomorrow when the time is not today."""
    clock = spoken_clock(moment)
    current = now or datetime.now().astimezone()
    if moment.date() == current.date():
        return clock
    if moment.date() == (current + timedelta(days=1)).date():
        return f"{clock} tomorrow"
    return f"{clock} on {moment.strftime('%b %d')}"


def when_from(text: str, now: datetime) -> datetime | None:
    """A clock time, a bare '6:00 PM', 'tomorrow', or 'in 20 minutes'. None when the words name no time."""
    found = _locate_when(text, now)
    return None if found is None else found[0]


def _duration_in(tail: str) -> tuple[int, str] | None:
    """Seconds, and the words after 'to' or 'for'. None when the tail names no length."""
    text = " ".join((tail or "").split())
    match = _DURATION_RE.match(text)
    if not match:
        return None
    seconds = _relative_seconds(match.group(1) or match.group(0))
    rest = text[match.end() :].strip()
    if seconds is None:
        return None
    purpose = ""
    led = re.match(r"(?:to|for)\s+(.+)$", rest)
    if led:
        purpose = led.group(1).strip(" .")
    elif rest:
        return None
    return seconds, purpose


def _timer_command(phrase: str, original: str) -> QuickCommand | None:
    match = re.search(r"\btimer(?:\s+for)?\s+(.+)$", phrase)
    if not match:
        return None
    parsed = _duration_in(match.group(1))
    if parsed is None:
        return None
    seconds, purpose = parsed
    if purpose:
        raw = re.search(rf"\b(?:to|for)\s+{re.escape(purpose)}\s*$", original, flags=re.IGNORECASE)
        if raw:
            purpose = original[raw.start() :].split(None, 1)[-1].strip(" .")
    return QuickCommand("timer", seconds=seconds, detail=purpose)


def _timer_as_reminder(phrase: str, original: str) -> QuickCommand | None:
    """'Set a timer' with no countdown is a reminder. A countdown is handled first."""
    for label in ("set a timer", "set timer", "start a timer", "start timer"):
        if phrase != label and not phrase.startswith(label + " "):
            continue
        now = datetime.now().astimezone()
        detail = _tail(original, label)
        located = _locate_when(detail, now) if detail else None
        if located is None and not detail:
            moment = now + timedelta(minutes=5)
            detail = "Timer"
            when = moment.isoformat(timespec="seconds")
        elif located is not None:
            moment, span = located
            detail = _cut_when(detail, span) or "Timer"
            when = moment.isoformat(timespec="seconds")
        else:
            when = ""
        return QuickCommand("remind", detail=detail or "Timer", when=when)
    return None


def _timer_seconds(phrase: str) -> int:
    match = re.search(r"timer(?: for)? (.+)$", phrase)
    if not match:
        return 0
    parsed = _duration_in(match.group(1))
    if parsed is None:
        return 0
    return parsed[0]


def timer_label(seconds: int) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
    return f"{seconds} second" if seconds == 1 else f"{seconds} seconds"
