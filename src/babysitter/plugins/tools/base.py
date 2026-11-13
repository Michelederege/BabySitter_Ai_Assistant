"""The shape every tool has to follow.

A tool does something beyond talking (a reminder, a search, a screen
look). The app must show the user exactly what will be sent, and wait
for a yes, before `run` is called.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ToolResult:
    spoken: str
    detail: str


class Tool(Protocol):
    id: str
    label: str

    def describe(self, arguments: dict) -> str:
        """One plain sentence: exactly what will happen if the user says yes."""

    def run(self, arguments: dict) -> ToolResult:
        """Do the thing. Only after the user has confirmed."""
