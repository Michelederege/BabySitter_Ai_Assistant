"""Ratings that adjust the tone on the next launch of the AI.

The standing instructions stay fixed during a session, so a rating is
saved now and read the next time the AI turns on. That keeps the model's
prefix cache warm. Nothing here is sent off this PC.
"""

from __future__ import annotations

import json

from babysitter.paths import data_dir


RATINGS = ("shorter", "longer", "warmer", "cooler", "just right")

_CLAUSES = {
    "shorter": "Prefer shorter answers than you otherwise would.",
    "longer": "You may use the full two or three sentences.",
    "warmer": "Sound a little warmer.",
    "cooler": "Sound a little cooler and more direct.",
    "just right": "Keep the current length and tone.",
}


def _path():
    return data_dir() / "ratings.json"


def load_counts() -> dict[str, int]:
    path = _path()
    if not path.is_file():
        return {name: 0 for name in RATINGS}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {name: 0 for name in RATINGS}
    counts = {name: 0 for name in RATINGS}
    if isinstance(raw, dict):
        for name in RATINGS:
            try:
                counts[name] = max(0, int(raw.get(name) or 0))
            except (TypeError, ValueError):
                counts[name] = 0
    return counts


def record(label: str) -> dict[str, int]:
    name = (label or "").strip().lower()
    if name not in RATINGS:
        raise ValueError(f"Unknown rating '{label}'.")
    counts = load_counts()
    counts[name] += 1
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return counts


def clause_from_counts(counts: dict[str, int]) -> str:
    best = ""
    best_count = 0
    for name in RATINGS:
        count = int(counts.get(name) or 0)
        if count > best_count:
            best = name
            best_count = count
    if not best:
        return ""
    return _CLAUSES[best]


def session_clause() -> str:
    """The sentence to add when the AI turns on. Empty when nothing is rated."""
    return clause_from_counts(load_counts())
