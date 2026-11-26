"""Decides when a game is running.

A game is noticed two ways: a name you typed (for example bg3.exe), or a
program running from a folder where game stores install (Steam's
steamapps, Epic Games, GOG, the Xbox app, Riot, or a folder simply named
Games). Only the program's file name and the folder it sits in are read.
It never reads a game's memory and never draws anything inside the game.
"""

from __future__ import annotations


# Folder names that game stores install into. The match is one whole
# folder in the path, not a part of a word.
STORE_FOLDERS = {
    "steamapps",
    "xboxgames",
    "gog games",
    "epic games",
    "riot games",
    "games",
}

# Programs that live inside those folders but are not the game itself.
NOT_THE_GAME = (
    "launcher",
    "riot client",
    "battle.net",
    "crashhandler",
    "crash handler",
    "crashreport",
    "easyanticheat",
    "anticheat",
    "vanguard",
    "redistributable",
    "vcredist",
    "directx",
    "dotnet",
    "unins",
    "setup",
    "installer",
)


def looks_like_game_path(path: str) -> bool:
    """True when this program file sits where game stores install games."""
    lowered = (path or "").replace("\\", "/").lower()
    if not lowered.endswith(".exe"):
        return False
    folders = [part.strip() for part in lowered.split("/")[:-1] if part.strip()]
    if not any(folder in STORE_FOLDERS for folder in folders):
        return False
    return not any(word in lowered for word in NOT_THE_GAME)


def detect_game(paths_by_name: dict[str, str]) -> str | None:
    """The first running program installed where games live, by name."""
    for name in sorted(paths_by_name):
        if looks_like_game_path(paths_by_name.get(name) or ""):
            return name
    return None


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


def should_hide_orb(
    enabled: bool,
    foreground: str | None,
    watchlist: list[str],
    detected_game: str | None = None,
) -> bool:
    """Hide BabySitter's own orb while a watched or detected game is the front window."""
    if not enabled or not foreground:
        return False
    if detected_game and foreground.lower() == detected_game.lower():
        return True
    return first_matching_game(watchlist, {foreground}) is not None


def foreground_window_title() -> str:
    """The front window's title. It is not written down."""
    import sys

    if sys.platform != "win32":
        return ""
    import ctypes

    user32 = ctypes.windll.user32
    window = user32.GetForegroundWindow()
    if not window:
        return ""
    length = int(user32.GetWindowTextLengthW(window))
    if length <= 0 or length > 300:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(window, buffer, length + 1)
    return buffer.value[:300]


def foreground_process_name() -> str | None:
    """The front program's file name on Windows. None anywhere else."""
    import sys

    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    window = user32.GetForegroundWindow()
    if not window:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
    if not pid.value:
        return None
    try:
        import psutil

        return psutil.Process(int(pid.value)).name()
    except (psutil.Error, OSError):
        return None


def first_matching_game(watchlist: list[str], running_names: set[str]) -> str | None:
    running_lower = {name.lower() for name in running_names}
    for entry in watchlist:
        if entry.lower() in running_lower:
            return entry
    return None
