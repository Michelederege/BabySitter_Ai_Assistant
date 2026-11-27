"""Saved conversations. They stay in the personal folder.

Home still keeps only the last few turns in memory. This file is the
record you can search, export, or delete later.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from babysitter.paths import data_dir
from babysitter.privatefile import read_private, seal_existing, write_private


def sessions_dir() -> Path:
    path = data_dir() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_id(session_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{10,32}", session_id or ""):
        raise ValueError("That conversation is not on this PC.")
    return session_id


def _path(session_id: str) -> Path:
    return sessions_dir() / f"{_safe_id(session_id)}.json"


def begin_session() -> str:
    session_id = uuid.uuid4().hex[:12]
    record = {
        "id": session_id,
        "started": datetime.now().astimezone().isoformat(timespec="minutes"),
        "turns": [],
    }
    _write(record)
    return session_id


def append_turn(session_id: str, user: str, assistant: str) -> None:
    record = load_session(session_id)
    record["turns"].append(
        {
            "user": (user or "")[:4000],
            "assistant": (assistant or "")[:8000],
        }
    )
    del record["turns"][:-200]
    _write(record)


def load_session(session_id: str) -> dict:
    path = _path(session_id)
    if not path.is_file():
        raise ValueError("That conversation is not on this PC.")
    try:
        raw = json.loads(read_private(path))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("That conversation could not be read.") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("turns"), list):
        raise ValueError("That conversation could not be read.")
    return raw


def _iter_session_records() -> list[tuple[dict, dict]]:
    """Read valid session files once, newest first, as (summary_row, full_record)."""
    found: list[tuple[dict, dict]] = []
    for path in sessions_dir().glob("*.json"):
        try:
            raw = json.loads(read_private(path))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(raw, dict):
            continue
        turns = raw.get("turns") if isinstance(raw.get("turns"), list) else []
        preview = ""
        if turns and isinstance(turns[0], dict):
            preview = str(turns[0].get("user") or "")[:80]
        summary = {
            "id": str(raw.get("id") or path.stem),
            "started": str(raw.get("started") or ""),
            "preview": preview,
            "turns": len(turns),
        }
        found.append((summary, raw))
    found.sort(key=lambda pair: pair[0]["started"], reverse=True)
    return found


def list_sessions() -> list[dict]:
    return [summary for summary, _raw in _iter_session_records()]


def search_sessions(query: str) -> list[dict]:
    needle = (query or "").strip().casefold()
    records = _iter_session_records()
    if not needle:
        return [summary for summary, _raw in records]
    matches: list[dict] = []
    for summary, record in records:
        turns = record.get("turns") if isinstance(record.get("turns"), list) else []
        blob = " ".join(
            f"{turn.get('user', '')} {turn.get('assistant', '')}"
            for turn in turns
            if isinstance(turn, dict)
        )
        if needle in blob.casefold() or needle in summary["started"].casefold():
            matches.append(summary)
    return matches


def export_text(session_id: str) -> Path:
    record = load_session(session_id)
    lines = [f"BabySitter conversation {record.get('started', '')}", ""]
    for turn in record["turns"]:
        if not isinstance(turn, dict):
            continue
        lines.append("You: " + str(turn.get("user") or ""))
        lines.append("BabySitter: " + str(turn.get("assistant") or ""))
        lines.append("")
    path = sessions_dir() / f"{_safe_id(session_id)}.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def delete_session(session_id: str) -> None:
    path = _path(session_id)
    text = path.with_suffix(".txt")
    path.unlink(missing_ok=True)
    text.unlink(missing_ok=True)


def wipe_sessions() -> int:
    count = 0
    for path in sessions_dir().glob("*"):
        if path.suffix not in {".json", ".txt"}:
            continue
        path.unlink(missing_ok=True)
        count += 1
    return count


def _write(record: dict) -> None:
    write_private(_path(str(record["id"])), json.dumps(record, indent=2) + "\n")


def seal_old_files() -> int:
    """Encrypt History and facts saved in plain text by a version before 0.27.0."""
    files = list(sessions_dir().glob("*.json")) + [data_dir() / "memory.json"]
    return seal_existing(path for path in files if path.is_file())
