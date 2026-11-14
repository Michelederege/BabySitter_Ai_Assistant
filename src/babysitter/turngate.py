"""Keeps slow background work out of a voice turn.

A reply already uses the processor for hearing, the model, and the voice.
A benchmark, a filler render, or a weekly scan waits until the turn ends.
Game-name checks are not this kind of job. They still run, so a game can
take the graphics card back.
"""

from __future__ import annotations

import threading
from collections.abc import Callable


class TurnGate:
    def __init__(self) -> None:
        self._depth = 0
        self._lock = threading.Lock()

    def enter(self) -> None:
        with self._lock:
            self._depth += 1

    def leave(self) -> None:
        with self._lock:
            self._depth = max(0, self._depth - 1)

    def busy(self) -> bool:
        with self._lock:
            return self._depth > 0


def run_if_idle(gate: TurnGate, job: Callable[[], None]) -> bool:
    """Run job when no voice turn is open. False means it was skipped."""
    if gate.busy():
        return False
    job()
    return True
