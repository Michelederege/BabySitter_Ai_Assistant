"""A daily journal of which program was in front. It stays on this PC.

About twice a minute, while the AI is on, the front program's file name
is written down — only the name. No window titles, no keys, no
screenshots, no addresses, and no network. Days are plain JSON files in
the personal folder, kept for 90 days, and a wipe deletes them all.
Tasks are only what you declare: "start task …" and "done".
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from babysitter.paths import data_dir


SAMPLE_SECONDS = 30
KEEP_DAYS = 90


def journal_dir() -> Path:
    path = data_dir() / "journal"
    path.mkdir(parents=True, exist_ok=True)
    return path


def day_path(day: date) -> Path:
    return journal_dir() / f"{day.isoformat()}.json"


def load_day(day: date) -> dict:
    path = day_path(day)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            raw = None
        if isinstance(raw, dict) and isinstance(raw.get("apps"), dict):
            raw.setdefault("tasks", [])
            return raw
    return {"date": day.isoformat(), "apps": {}, "tasks": []}


def save_day(record: dict) -> None:
    path = journal_dir() / f"{record['date']}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def plain_app(name: str) -> str:
    """bg3.exe becomes bg3. Spoken lines do not need the .exe."""
    base = (name or "").strip()
    if base.lower().endswith(".exe"):
        base = base[:-4]
    return base


def record_sample(
    record: dict,
    app: str,
    moment: datetime,
    seconds: int = SAMPLE_SECONDS,
    excluded: list[str] | None = None,
) -> bool:
    """Add one sample. Returns False when the app is excluded or empty."""
    name = plain_app(app).lower()
    if not name or len(name) > 120:
        return False
    for item in excluded or []:
        if plain_app(str(item)).lower() == name:
            return False
    stamp = moment.isoformat(timespec="minutes")
    entry = record["apps"].setdefault(name, {"seconds": 0, "first": stamp, "last": stamp})
    entry["seconds"] = int(entry.get("seconds") or 0) + int(seconds)
    entry["last"] = stamp
    return True


def start_task(record: dict, name: str, moment: datetime) -> str:
    """Open a named block. An already-open task is finished first."""
    title = " ".join((name or "").split())[:120]
    if not title:
        return "Say the task's name, like start task modeling the bracket."
    closing = finish_task(record, moment, quiet=True)
    record["tasks"].append(
        {"name": title, "start": moment.isoformat(timespec="minutes"), "end": ""}
    )
    opening = f"Started {title}. Say done when you finish."
    if closing:
        return f"{closing} {opening}"
    return opening


def finish_task(record: dict, moment: datetime, quiet: bool = False) -> str:
    for task in reversed(record.get("tasks") or []):
        if isinstance(task, dict) and not task.get("end"):
            task["end"] = moment.isoformat(timespec="minutes")
            label = span_label(_task_seconds(task))
            return f"Done. {task.get('name', 'The task')} took {label}."
    if quiet:
        return ""
    return "No task is open. Say start task and its name first."


def _task_seconds(task: dict) -> int:
    try:
        start = datetime.fromisoformat(str(task.get("start")))
        end = datetime.fromisoformat(str(task.get("end")))
    except (TypeError, ValueError):
        return 0
    return max(0, int((end - start).total_seconds()))


def span_label(seconds: int) -> str:
    total = max(0, int(seconds))
    if total < 60:
        return "under a minute"
    hours, rest = divmod(total, 3600)
    minutes = rest // 60
    parts: list[str] = []
    if hours:
        parts.append("1 hour" if hours == 1 else f"{hours} hours")
    if minutes:
        parts.append("1 minute" if minutes == 1 else f"{minutes} minutes")
    return " ".join(parts) or "under a minute"


def _clock(stamp: str) -> str:
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return ""
    return moment.strftime("%I:%M %p").lstrip("0")


def ranked_apps(record: dict, floor_seconds: int = 60) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for name, entry in (record.get("apps") or {}).items():
        if not isinstance(entry, dict):
            continue
        seconds = int(entry.get("seconds") or 0)
        if seconds >= floor_seconds:
            rows.append((str(name), seconds))
    rows.sort(key=lambda row: row[1], reverse=True)
    return rows


def day_speech(record: dict, day_word: str = "today", top: int = 3) -> str:
    apps = ranked_apps(record)
    tasks = [task for task in record.get("tasks") or [] if isinstance(task, dict)]
    if not apps and not tasks:
        return (
            f"Nothing is in the journal for {day_word}. "
            "It writes down the front program while the AI is on."
        )
    parts: list[str] = []
    if apps:
        spoken = ", ".join(f"{span_label(seconds)} in {name}" for name, seconds in apps[:top])
        parts.append(f"{day_word.capitalize()} you spent {spoken}.")
        if len(apps) > top:
            parts.append(f"{len(apps) - top} more are on the screen.")
    done = [task for task in tasks if task.get("end")]
    if done:
        names = ", ".join(str(task.get("name") or "a task") for task in done[:3])
        parts.append(f"Finished: {names}.")
    for task in reversed(tasks):
        if not task.get("end"):
            parts.append(f"Still open: {task.get('name')}.")
            break
    return " ".join(parts)


def day_detail(record: dict) -> str:
    lines: list[str] = []
    for name, seconds in ranked_apps(record, floor_seconds=1):
        entry = record["apps"][name]
        first = _clock(str(entry.get("first") or ""))
        last = _clock(str(entry.get("last") or ""))
        window = f" ({first} to {last})" if first and last and first != last else ""
        lines.append(f"{name} — {span_label(seconds)}{window}")
    tasks = [task for task in record.get("tasks") or [] if isinstance(task, dict)]
    if tasks:
        lines.append("")
        lines.append("Tasks:")
        for task in tasks:
            start = _clock(str(task.get("start") or ""))
            if task.get("end"):
                lines.append(
                    f"{task.get('name')} — {span_label(_task_seconds(task))}, started {start}"
                )
            else:
                lines.append(f"{task.get('name')} — still open, started {start}")
    if not lines:
        return "Nothing recorded. The journal writes while the AI is on."
    lines.append("")
    lines.append("Only program names and minutes. Nothing left this PC.")
    return "\n".join(lines)


def prune(today: date, keep_days: int = KEEP_DAYS) -> int:
    """Delete day files older than the keep window. Returns how many."""
    removed = 0
    for path in journal_dir().glob("*.json"):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if (today - day).days > keep_days:
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def wipe() -> int:
    removed = 0
    for path in journal_dir().glob("*.json"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed
