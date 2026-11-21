"""Timings for a voice turn. Words are never stored here."""

from __future__ import annotations

import time


class TurnClock:
    """One turn, measured from the moment the question is ready to send."""

    def __init__(self) -> None:
        self._t0 = time.perf_counter()
        self.marks: dict[str, int] = {}

    def mark(self, name: str) -> None:
        if name not in self.marks:
            self.marks[name] = int((time.perf_counter() - self._t0) * 1000)

    def as_row(self) -> dict[str, int]:
        return {key: value for key, value in self.marks.items() if isinstance(value, int)}


class ResponsivenessLog:
    """The last voice turns, as milliseconds only."""

    KEYS = (
        "transcript",
        "first_token",
        "first_phrase",
        "first_sound",
        "interrupt",
        "prompt_tokens",
        "gen_tokens",
        "prompt_tps",
        "gen_tps",
        "load_ms",
        "image_tokens",
    )

    def __init__(self) -> None:
        self.rows: list[dict[str, int]] = []

    def add(self, row: dict) -> None:
        clean: dict[str, int] = {}
        for key in self.KEYS:
            value = row.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                clean[key] = value
        if not clean:
            return
        self.rows.append(clean)
        del self.rows[:-20]

    def summary(self) -> str:
        sounds = [row["first_sound"] for row in self.rows if "first_sound" in row]
        if not sounds:
            return "No voice turns measured yet. Only timings are kept. No words are stored."
        ordered = sorted(sounds)
        typical = ordered[(len(ordered) - 1) // 2]
        worst = ordered[-1]
        line = (
            f"Typical time to first sound: {typical} ms. Worst: {worst} ms. "
            f"{len(sounds)} turns. Only timings are kept. No words are stored."
        )
        prompts = [row["prompt_tokens"] for row in self.rows if "prompt_tokens" in row]
        if prompts:
            line += f" Last reply read {prompts[-1]} prompt tokens."
        ready = [row["transcript"] for row in self.rows if "transcript" in row]
        if ready:
            line += f" Last line became text after {ready[-1]} ms."
        return line

    def export_text(self) -> str:
        lines = [
            "BabySitter responsiveness",
            "Timings in milliseconds. No words are included.",
            self.summary(),
            "",
        ]
        if not self.rows:
            lines.append("No turns yet.")
            return "\n".join(lines) + "\n"
        for index, row in enumerate(self.rows, start=1):
            parts = [f"{key}={row[key]}" for key in self.KEYS if key in row]
            lines.append(f"Turn {index}: " + ", ".join(parts))
        return "\n".join(lines) + "\n"
