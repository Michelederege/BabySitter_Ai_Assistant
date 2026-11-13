"""Decides when a chosen game is running.

This looks only at the program's file name (for example bg3.exe).
It never reads a game's memory and never draws anything inside the game.
"""

from __future__ import annotations


class GameWatch:
    """Remembers if you woke the model while a game was still open."""

    def __init__(self) -> None:
        self.suppressed: str | None = None

    def suppress(self, process_name: str | None) -> None:
        self.suppressed = process_name

    def clear_if_gone(self, running_match: str | None) -> None:
        if running_match is None:
            self.suppressed = None

    def auto_switch_target(self, running_match: str | None) -> str | None:
        """The game that should force game mode, or None to leave you alone."""
        self.clear_if_gone(running_match)
        if running_match is None:
            return None
        if self.suppressed and running_match.lower() == self.suppressed.lower():
            return None
        return running_match


def clean_process_name(name: str) -> str:
    """Keep a program name like 'game.exe', never a path or a command."""
    trimmed = name.strip().strip('"').strip()
    if not trimmed:
        raise ValueError("Type the program name, for example game.exe.")
    # Treat both Windows and other paths the same, so a pasted path
    # becomes just the program name (bg3.exe).
    base = trimmed.replace("\\", "/").split("/")[-1]
    if base in {".", ".."} or not base:
        raise ValueError("That is not a program name.")
    if any(character in base for character in '\\/:*?"<>|'):
        raise ValueError("A program name cannot include \\ / : * ? \" < > |.")
    if len(base) > 120:
        raise ValueError("That program name is too long.")
    return base


def first_matching_game(watchlist: list[str], running_names: set[str]) -> str | None:
    running_lower = {name.lower() for name in running_names}
    for entry in watchlist:
        if entry.lower() in running_lower:
            return entry
    return None
