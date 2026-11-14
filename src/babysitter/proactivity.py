"""How far BabySitter leans forward after an answer.

0 answers and stops.
1 reminds you that more is on the screen. This is the default.
2 can point at one saved fact that matches.
3 can also mention the weekly review, once, until you ask for it.

The review itself is written from files on this PC. It does not load a model.
"""

from __future__ import annotations

from datetime import date


def offer_more(level: int, has_rest: bool) -> bool:
    return int(level) >= 1 and bool(has_rest)


def offer_fact(level: int, fact: str) -> str:
    if int(level) >= 2 and (fact or "").strip():
        return fact.strip()
    return ""


def offer_weekly(level: int, last_iso: str, today: date, already_offered: bool) -> bool:
    if already_offered or int(level) < 3:
        return False
    text = (last_iso or "").strip()
    if not text:
        return True
    try:
        last = date.fromisoformat(text)
    except ValueError:
        return True
    return (today - last).days >= 7


def nudge(level: int, has_rest: bool, fact: str, weekly: bool) -> str:
    parts: list[str] = []
    if offer_more(level, has_rest):
        parts.append("Say yes to hear the rest.")
    shown = offer_fact(level, fact)
    if shown:
        parts.append(f"A saved fact may matter: {shown}")
    if weekly:
        parts.append("The weekly review is ready. Say weekly review.")
    return " ".join(parts)


def weekly_review(memories: list[str], notes: list[str]) -> str:
    """A local summary. No model, no graphics card, no network."""
    kept = [item.strip() for item in memories if item and item.strip()][:8]
    recent = [item.strip() for item in notes if item and item.strip()][:5]
    lines = ["Here is the week on this PC. No model was loaded for this."]
    if kept:
        lines.append("Saved facts: " + "; ".join(kept) + ".")
    else:
        lines.append("No saved facts.")
    if recent:
        lines.append("Recent notes: " + "; ".join(recent) + ".")
    return " ".join(lines)
