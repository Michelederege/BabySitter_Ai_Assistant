"""Requests BabySitter could not do yet, kept so they can be built later.

When he asks for something it can't do, the request is saved here. The
sheet says at the top that a request is taken off once it's built into the
app. That happens two ways:

* each time a new version starts, every saved request is tried against the
  commands again, and the ones it can do now are removed (and he is told);
* whoever builds one by hand removes it with "remove request 2", the
  Remove button, or by deleting its line from requests.json.

Only the words of the request are kept, on this PC, with the day it was asked.
"""

from __future__ import annotations

import re
from datetime import date

FILE = "requests.json"
SHEET_HEADER = (
    "Things you asked for that BabySitter can't do yet. "
    "When one of these is built into the app, it's taken off this list."
)

# The reply said it couldn't. Matched on the model's own reply, only for a
# line that was a request (see looks_like_request).
_CANNOT = re.compile(
    r"\b(?:i\s+)?(?:can'?t|cannot|can not|am not able to|'m not able to|am unable to|'m unable to|don'?t have (?:a way|the ability|access))\b"
    r"|\bisn'?t something i can do\b|\bnot something i can do\b|\bbeyond what i can do\b",
    re.IGNORECASE,
)
_REQUEST_START = re.compile(
    r"^(?:(?:hey|ok(?:ay)?|so|please|kari)[\s,]+)*"
    r"(?:can you|could you|would you|will you|please|i want you to|i need you to|i'?d like you to|"
    r"go ahead and|make|set|turn|open|close|play|send|text|call|email|order|book|buy|start|stop|"
    r"change|add|delete|remove|move|show|put|schedule|download|install|record|translate|draw|"
    r"connect|sync|mute|pause|lock|shut|restart|launch|create|write|copy|paste|save|print)\b",
    re.IGNORECASE,
)

# Explicit: "I wish you could …", "add to my requests: …", "save this as a request: …".
_EXPLICIT = re.compile(
    r"^(?:i wish (?:you|babysitter) could|it would be (?:nice|great|cool) if you could|"
    r"(?:add|put|save)(?: this| that)?(?: to| on| as)? (?:my |the )?(?:requests?|wish ?list|feature requests?)(?: list)?|"
    r"(?:new|feature) request)\s*[:,-]?\s+(.+)$",
    re.IGNORECASE,
)


def looks_like_request(line: str) -> bool:
    """A line asking BabySitter to do something, not a question about the world."""
    text = " ".join((line or "").split())
    if not text or text.endswith("?") and not re.match(r"^(?:can|could|would|will) you\b", text, re.IGNORECASE):
        return False
    return bool(_REQUEST_START.match(text))


def reply_says_cannot(reply: str) -> bool:
    return bool(_CANNOT.search(reply or ""))


def explicit_request(line: str) -> str:
    """The request in "I wish you could …" or "add to my requests: …", or ""."""
    found = _EXPLICIT.match(" ".join((line or "").split()).rstrip(".!"))
    if not found:
        return ""
    return found.group(1).strip(" .,:")


def _key(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", (text or "").lower()))


def add(items: list[dict], text: str, today: date | None = None) -> tuple[list[dict], bool]:
    """The list with the request added. False when the same words were already there."""
    words = " ".join((text or "").split())[:300]
    if not words:
        return items, False
    key = _key(words)
    for item in items:
        if _key(str(item.get("text") or "")) == key:
            item["times"] = int(item.get("times") or 1) + 1
            return items, False
    from uuid import uuid4

    items = list(items) + [
        {"id": uuid4().hex[:10], "text": words, "asked": (today or date.today()).isoformat(), "times": 1}
    ]
    return items, True


def remove_number(items: list[dict], number: int) -> tuple[list[dict], dict | None]:
    """Remove the request at its shown number (1 is the first)."""
    if number < 1 or number > len(items):
        return items, None
    kept = list(items)
    gone = kept.pop(number - 1)
    return kept, gone


def now_possible(items: list[dict], can_do) -> tuple[list[dict], list[dict]]:
    """Split into (still wanted, built since). can_do(text) says whether a command handles it now."""
    kept: list[dict] = []
    built: list[dict] = []
    for item in items:
        text = str(item.get("text") or "")
        try:
            done = bool(text) and bool(can_do(text))
        except Exception:
            done = False
        (built if done else kept).append(item)
    return kept, built


def sheet_lines(items: list[dict]) -> list[str]:
    """The sheet as shown: the header, then each request with its number and day."""
    lines = [SHEET_HEADER, ""]
    if not items:
        lines.append("Nothing saved yet. When I can't do something you ask, it's added here.")
        return lines
    for number, item in enumerate(items, start=1):
        times = int(item.get("times") or 1)
        asked = f" ({times} times)" if times > 1 else ""
        lines.append(f"{number}. {item.get('text', '')} — asked {item.get('asked', '')}{asked}")
    return lines


def spoken_list(items: list[dict]) -> str:
    if not items:
        return "Your requests list is empty."
    first = [str(item.get("text") or "") for item in items[:3]]
    count = len(items)
    lead = "You have one request saved: " if count == 1 else f"You have {count} requests saved. "
    if count == 1:
        return lead + first[0] + "."
    return lead + "The first ones: " + "; ".join(first) + "."
