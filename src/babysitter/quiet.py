"""Quiet hours. While they are on, the AI refuses to turn on.

Emergency stop still works. The window stays usable so the hours can
be turned off.
"""

from __future__ import annotations

from datetime import datetime, time


def parse_hhmm(value: str) -> time:
    text = (value or "").strip()
    parts = text.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("Use a time like 22:00.")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour > 23 or minute > 59:
        raise ValueError("Use a time like 22:00.")
    return time(hour, minute)


def in_quiet_hours(enabled: bool, start: str, end: str, now: datetime | None = None) -> bool:
    if not enabled:
        return False
    try:
        begin = parse_hhmm(start)
        finish = parse_hhmm(end)
    except ValueError:
        return False
    moment = (now or datetime.now()).time().replace(second=0, microsecond=0)
    if begin == finish:
        return False
    if begin < finish:
        return begin <= moment < finish
    return moment >= begin or moment < finish


def quiet_sentence(start: str, end: str) -> str:
    return (
        f"Quiet hours are {start} to {end}. The AI stays off. "
        "Turn quiet hours off in Settings to start it."
    )
