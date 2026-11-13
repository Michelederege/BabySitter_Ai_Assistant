"""Pins, reminders, and memories. All of them stay in the personal folder.

Nothing in this file is sent anywhere. A wipe of the personal folder
removes them with the rest of your BabySitter files.
"""

from __future__ import annotations

import json
import uuid
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


def remove_item(name: str, item_id: str) -> None:
    items = [item for item in load_list(name) if item.get("id") != item_id]
    save_list(name, items)


def hero_path() -> Path:
    return data_dir() / "hero.png"
