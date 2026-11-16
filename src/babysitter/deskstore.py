"""Pins, reminders, and memories. All of them stay in the personal folder.

Nothing in this file is sent anywhere. A wipe of the personal folder
removes them with the rest of your BabySitter files.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from babysitter.paths import data_dir


def load_list(name: str) -> list[dict]:
    path = data_dir() / name
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def save_list(name: str, items: list[dict]) -> None:
    path = data_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def add_item(name: str, **fields: str) -> dict:
    items = load_list(name)
    item = {"id": uuid.uuid4().hex[:10], **fields}
    items.append(item)
    save_list(name, items)
    return item


def remaining_clock(due: str, now: datetime | None = None, fired: str = "") -> str:
    """Time left until a reminder rings. Empty when it has no clock or was already said."""
    if str(fired or "") == "yes":
        return ""
    text = (due or "").strip()
    if not text:
        return ""
    moment_now = now or datetime.now().astimezone()
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=moment_now.tzinfo)
    seconds = int((moment - moment_now).total_seconds())
    if seconds <= 0:
        return "now"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def reminder_line(item: dict, now: datetime | None = None) -> str:
    """One reminder as it should read on the Reminders page, including the time left."""
    text = " ".join(str(item.get("text") or "").split()) or "Reminder"
    due = str(item.get("due") or "").strip()
    fired = str(item.get("fired") or "")
    clock = ""
    if due:
        try:
            moment = datetime.fromisoformat(due)
            clock = moment.strftime("%a %I:%M %p").replace(" 0", " ")
        except ValueError:
            clock = due
    line = text
    if clock and clock not in text:
        line = f"{clock} — {text}"
    left = remaining_clock(due, now, fired)
    if left:
        line += f" — {left}"
    if fired == "yes":
        line += " — already said"
    return line


def next_reminder_line(items: list[dict], now: datetime | None = None) -> str:
    """The soonest reminder that is still counting, for the line on Home."""
    moment_now = now or datetime.now().astimezone()
    waiting: list[tuple[datetime, dict]] = []
    untimed = 0
    for item in items:
        if str(item.get("fired") or "") == "yes":
            continue
        due = str(item.get("due") or "").strip()
        if not due:
            untimed += 1
            continue
        try:
            moment = datetime.fromisoformat(due)
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=moment_now.tzinfo)
        waiting.append((moment, item))
    if not waiting:
        if untimed:
            return "A reminder is saved with no clock, so it is not counting down."
        return "No reminder is counting down."
    waiting.sort(key=lambda pair: pair[0])
    _moment, item = waiting[0]
    left = remaining_clock(str(item.get("due") or ""), moment_now)
    words = " ".join(str(item.get("text") or "Reminder").split()) or "Reminder"
    extra = ""
    if len(waiting) > 1:
        more = len(waiting) - 1
        extra = f" {more} more counting down." if more > 1 else " 1 more counting down."
    return f"{words} — {left}{extra}"


def remove_item(name: str, item_id: str) -> None:
    items = [item for item in load_list(name) if item.get("id") != item_id]
    save_list(name, items)


def hero_path() -> Path:
    return data_dir() / "hero.png"
