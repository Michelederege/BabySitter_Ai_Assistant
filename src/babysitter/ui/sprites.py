"""The frog sprite strips, shared by the orb and the picture on Home.

Each strip is decoded only when its state is first drawn, and the orb and
the picture share the one copy. Decoding all eight at start, once for each
of the two frogs, cost about 126 MB of memory for frames that were mostly
never shown; the frog that is Off needs only the Off strip (about 12 MB).
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtGui import QPixmap

_SHEETS: dict[str, "FrogStrips"] = {}


class FrogStrips:
    """A read-only mapping of state -> (pixmap, frames) that loads on first use."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.frame_px = 0
        self.fps = 0
        self._files: dict[str, tuple[str, int]] = {}
        self._loaded: dict[str, tuple[QPixmap, int]] = {}
        self._broken: set[str] = set()
        try:
            meta = json.loads((self.folder / "sprites.json").read_text(encoding="utf-8"))
            self.frame_px = int(meta["frameSize"])
            self.fps = int(meta["fps"])
            for state, info in meta["states"].items():
                self._files[str(state)] = (str(info["file"]), int(info["frames"]))
        except Exception:  # noqa: BLE001 - no sprites: the frogs fall back to a plain light
            self._files = {}

    def __bool__(self) -> bool:
        return bool(self._files)

    def __iter__(self):
        """Every state that has a strip on disk, loaded or not."""
        return iter(self._files)

    def __contains__(self, state: object) -> bool:
        return state in self._files and state not in self._broken

    def __getitem__(self, state: str) -> tuple[QPixmap, int]:
        found = self.get(state)
        if found is None:
            raise KeyError(state)
        return found

    def get(self, state, default=None):
        if state in self._loaded:
            return self._loaded[state]
        if state not in self._files or state in self._broken:
            return default
        name, frames = self._files[state]
        pixmap = QPixmap(str(self.folder / name))
        if pixmap.isNull():
            self._broken.add(state)
            return default
        self._loaded[state] = (pixmap, frames)
        return self._loaded[state]

    def loaded_states(self) -> list[str]:
        return list(self._loaded)


def frog_strips(folder: Path) -> FrogStrips:
    """The one shared set of strips for this folder."""
    key = str(Path(folder).resolve())
    sheet = _SHEETS.get(key)
    if sheet is None:
        sheet = FrogStrips(Path(folder))
        _SHEETS[key] = sheet
    return sheet
