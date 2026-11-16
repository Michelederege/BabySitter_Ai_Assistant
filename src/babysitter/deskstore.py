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


def reminder_line(item: dict) -> str:
    """One reminder as it should read on the Reminders page."""
    text = " ".join(str(item.get("text") or "").split()) or "Reminder"
    due = str(item.get("due") or "").strip()
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
    if str(item.get("fired") or "") == "yes":
        line += " — already said"
    return line


def remove_item(name: str, item_id: str) -> None:
    items = [item for item in load_list(name) if item.get("id") != item_id]
    save_list(name, items)


def hero_path() -> Path:
    return data_dir() / "hero.png"
