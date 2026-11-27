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
    """The sentences to add when the AI turns on: the rating, then the persona."""
    parts = [clause_from_counts(load_counts()), persona_clause()]
    return " ".join(part for part in parts if part)


# A persona is one saved sentence. It changes how the assistant speaks and
# nothing else: the tools stay the tools, and every action still needs
# your command and its confirm.
PERSONAS = {
    "edith": (
        "Your name is EDITH. Speak calmly and precisely, with quiet confidence and a dry, "
        "understated wit. Be brief and exact, like a capable assistant who has already checked the details."
    ),
}
PERSONA_LIMITS = (
    " The name changes only how you speak. You still cannot send mail, change a calendar, "
    "press play, flip a switch, or invent a source."
)


def _persona_path():
    return data_dir() / "persona.json"


def clean_persona_name(name: str) -> str:
    words = [word for word in "".join(c if c.isalpha() or c in " '-" else " " for c in (name or "")).split() if word]
    if not 1 <= len(words) <= 2 or len(" ".join(words)) > 24:
        raise ValueError("Use a short name, one or two words.")
    return " ".join(word.capitalize() for word in words)


def persona_sentence(name: str) -> str:
    shown = clean_persona_name(name)
    preset = PERSONAS.get(shown.lower())
    if preset:
        return preset + PERSONA_LIMITS
    return f"Your name is {shown}. Answer to that name and keep your usual manner." + PERSONA_LIMITS


def save_persona(name: str) -> str:
    """Save the persona. Returns its name as it will be shown."""
    shown = clean_persona_name(name)
    path = _persona_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"name": shown}) + "\n", encoding="utf-8")
    temporary.replace(path)
    return "EDITH" if shown.lower() == "edith" else shown


def clear_persona() -> None:
    _persona_path().unlink(missing_ok=True)


def persona_name() -> str:
    try:
        raw = json.loads(_persona_path().read_text(encoding="utf-8"))
        return clean_persona_name(str(raw.get("name") or "")) if isinstance(raw, dict) else ""
    except (OSError, ValueError, UnicodeError):
        return ""


def persona_clause() -> str:
    name = persona_name()
    return persona_sentence(name) if name else ""
