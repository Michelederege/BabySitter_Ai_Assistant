"""Fit the AI beside a running game, by how much memory the game leaves.

Every two seconds the status check reads the graphics card. The room the
AI has is the card's total minus what everything else is using. Its own
model does not count against it. From that room:

- the level you picked still fits: nothing changes;
- a lower level fits: switch down to it, for as long as the game runs;
- not even Low fits: game mode, which unloads the model.

A verdict has to hold for a few readings before anything switches, so a
loading screen does not flip levels. While a game runs the level only
goes down. When the game has been closed for a while, the level you
picked comes back, and game mode that was switched on here is left.
"""

from __future__ import annotations

from dataclasses import dataclass

from babysitter.intelligence import MODES

# Highest first. A level is never raised above the one you picked.
ORDER = ("high", "medium", "low")

# Readings in a row before a change. The status check runs every 2 s.
SETTLE_READINGS = 3
CLOSED_READINGS = 5

# Less free system memory than this while a game runs means no level fits.
RAM_FLOOR_BYTES = 1024 ** 3


def room_mib(total_mib: int, used_mib: int, ours_mib: int) -> int:
    """Video memory the AI could use: everything except what others hold."""
    others = max(0, int(used_mib) - max(0, int(ours_mib)))
    return max(0, int(total_mib) - others)


def fitting_level(chosen: str, room: int) -> str | None:
    """The highest level at or below the one you picked that fits the room."""
    start = ORDER.index(chosen) if chosen in ORDER else ORDER.index("medium")
    for level in ORDER[start:]:
        if MODES[level].vram_mib <= room:
            return level
    return None


@dataclass(frozen=True)
class Action:
    kind: str  # "none", "lower", "game", "restore", "leave_game"
    level: str = ""
    reason: str = ""


NOTHING = Action("none")


class GameBudget:
    """Remembers what a game made BabySitter give up, so it can be returned."""

    def __init__(self) -> None:
        self.restore_to = ""  # the level to bring back when the game closes
        self.auto_game = False  # game mode was switched on here, not by you
        self._pending: tuple[str, str] | None = None
        self._pending_count = 0
        self._closed_count = 0

    def entered_game(self, chosen: str) -> None:
        """Game mode was switched on here. Leave it when the game closes."""
        self.auto_game = True
        self.restore_to = self.restore_to or chosen

    def forget(self) -> None:
        """You chose a level or a mode by hand. That choice stands."""
        self.restore_to = ""
        self.auto_game = False
        self._pending = None
        self._pending_count = 0
        self._closed_count = 0

    def _settled(self, verdict: tuple[str, str]) -> bool:
        if verdict == self._pending:
            self._pending_count += 1
        else:
            self._pending = verdict
            self._pending_count = 1
        return self._pending_count >= SETTLE_READINGS

    def decide(
        self,
        *,
        game: str | None,
        state: str,
        chosen: str,
        loaded: str,
        gpu: tuple[int, int, int] | None,
        ram_free: int | None,
        may_unload: bool = True,
    ) -> Action:
        """One reading. `gpu` is (total, used, ours) in MB, or None when unknown."""
        if game is None:
            self._pending = None
            self._pending_count = 0
            if not self.restore_to and not self.auto_game:
                return NOTHING
            self._closed_count += 1
            if self._closed_count < CLOSED_READINGS:
                return NOTHING
            self._closed_count = 0
            if state == "game" and self.auto_game:
                self.auto_game = False
                self.restore_to = ""
                return Action("leave_game", chosen, "The game closed.")
            if state == "on" and self.restore_to and loaded != self.restore_to:
                level = self.restore_to
                self.restore_to = ""
                return Action("restore", level, "The game closed.")
            self.restore_to = ""
            self.auto_game = False
            return NOTHING

        self._closed_count = 0
        if state != "on":
            return NOTHING
        if gpu is None:
            # The card cannot be read, so the room is unknown. Game mode, as before.
            if not may_unload or not self._settled(("game", "")):
                return NOTHING
            self._pending = None
            return Action("game", "", f"{game} is running, and the video memory could not be read.")

        total, used, ours = gpu
        room = room_mib(total, used, ours)
        low_ram = ram_free is not None and ram_free < RAM_FLOOR_BYTES
        # Only down while the game runs. The ceiling is what is loaded now.
        ceiling = loaded if loaded in ORDER else chosen
        level = None if low_ram else fitting_level(ceiling, room)
        if level == ceiling:
            self._pending = None
            self._pending_count = 0
            return NOTHING
        if level is None:
            if not may_unload or not self._settled(("game", "")):
                return NOTHING
            self._pending = None
            why = "system memory is nearly full" if low_ram else f"only about {room:,} MB of video memory is left"
            return Action("game", "", f"{game} is running and {why}.")
        if not self._settled(("lower", level)):
            return NOTHING
        self._pending = None
        self.restore_to = self.restore_to or chosen
        return Action(
            "lower",
            level,
            f"{game} is using the graphics card. About {room:,} MB is left, so "
            f"{MODES[level].label} fits and {MODES[ceiling].label} does not.",
        )
