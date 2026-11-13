"""Turns words like Ctrl+Alt+F12 into a Windows hotkey.

RegisterHotKey is the least invasive keyboard hook: Windows watches that
one combination and leaves every other key alone. It cannot see mouse
side buttons. A mouse button, if you want one later, needs a different
method and will be off whenever the AI is off or a game is in front.
"""

from __future__ import annotations

from dataclasses import dataclass


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

EMERGENCY_ID = 1
POWER_ON_ID = 2

# Shortcuts people need for typing, copying, and closing a window.
BLOCKED = {
    "CTRL+C",
    "CTRL+V",
    "CTRL+X",
    "CTRL+Z",
    "CTRL+A",
    "CTRL+S",
    "CTRL+Y",
    "ALT+F4",
    "CTRL+ESC",
    "CTRL+ALT+DELETE",
    "ALT+TAB",
}


class HotkeyError(ValueError):
    """The chosen keys are missing, blocked, or not understood."""


def _vk_for(key: str) -> int:
    upper = key.upper()
    if upper.startswith("F") and upper[1:].isdigit():
        number = int(upper[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    if len(upper) == 1 and "A" <= upper <= "Z":
        return ord(upper)
    if len(upper) == 1 and upper.isdigit():
        return ord(upper)
    raise HotkeyError(
        f"I don't know the key '{key}'. Use a letter, a number, or F1 through F24."
    )


def parse_hotkey(text: str) -> tuple[int, int, str]:
    """Return Windows modifier flags (with no-repeat), virtual key, and a clean label."""
    parts = [part.strip() for part in text.replace("-", "+").split("+") if part.strip()]
    if len(parts) < 2:
        raise HotkeyError("Use at least one modifier, such as Ctrl+Alt+F12.")
    modifiers = 0
    key_name = None
    for part in parts[:-1]:
        token = part.upper()
        if token in {"CTRL", "CONTROL"}:
            modifiers |= MOD_CONTROL
        elif token == "ALT":
            modifiers |= MOD_ALT
        elif token == "SHIFT":
            modifiers |= MOD_SHIFT
        elif token in {"WIN", "WINDOWS", "META"}:
            modifiers |= MOD_WIN
        else:
            raise HotkeyError(f"'{part}' is not Ctrl, Alt, Shift, or Win.")
    key_name = parts[-1]
    if modifiers == 0:
        raise HotkeyError("Add Ctrl, Alt, Shift, or the Windows key so typing still works.")
    label = _canonical_from_parts(modifiers, key_name)
    if label.upper() in BLOCKED:
        raise HotkeyError(f"{label} is reserved for Windows or for editing text. Pick another.")
    vk = _vk_for(key_name)
    return modifiers | MOD_NOREPEAT, vk, label


def _canonical_from_parts(modifiers: int, key_name: str) -> str:
    pieces: list[str] = []
    if modifiers & MOD_CONTROL:
        pieces.append("Ctrl")
    if modifiers & MOD_ALT:
        pieces.append("Alt")
    if modifiers & MOD_SHIFT:
        pieces.append("Shift")
    if modifiers & MOD_WIN:
        pieces.append("Win")
    key = key_name.upper()
    if len(key) == 1:
        pieces.append(key)
    else:
        pieces.append(key[0].upper() + key[1:].lower() if key.startswith("F") else key)
        if key.startswith("F"):
            pieces[-1] = key
    return "+".join(pieces)


def canonical_hotkey(text: str) -> str:
    _mods, _vk, label = parse_hotkey(text)
    return label


@dataclass
class RegisteredHotkey:
    hotkey_id: int
    label: str


class HotkeyBook:
    """Tracks which keys are reserved. The Windows call sits behind `registrar`."""

    def __init__(self) -> None:
        self.assistant_enabled = False
        self.registered: dict[int, str] = {}

    def set_assistant_enabled(self, enabled: bool) -> None:
        """Future push-to-talk keys follow this. Emergency and On do not."""
        self.assistant_enabled = enabled

    def apply(self, emergency: str, power_on: str, registrar) -> list[str]:
        if canonical_hotkey(emergency).lower() == canonical_hotkey(power_on).lower():
            raise HotkeyError("The emergency key and the turn-on key must be different.")
        notes: list[str] = []
        registrar.clear()
        self.registered.clear()
        for hotkey_id, text in ((EMERGENCY_ID, emergency), (POWER_ON_ID, power_on)):
            modifiers, vk, label = parse_hotkey(text)
            ok, detail = registrar.register(hotkey_id, modifiers, vk)
            if ok:
                self.registered[hotkey_id] = label
            else:
                notes.append(f"Could not reserve {label}. {detail}")
        return notes


class MemoryRegistrar:
    """Remembers registrations without calling Windows. Used in tests."""

    def __init__(self, failures: set[int] | None = None) -> None:
        self.failures = failures or set()
        self.active: dict[int, tuple[int, int]] = {}

    def register(self, hotkey_id: int, modifiers: int, vk: int) -> tuple[bool, str]:
        if hotkey_id in self.failures:
            return False, "Another program may be using it."
        self.active[hotkey_id] = (modifiers, vk)
        return True, ""

    def clear(self) -> None:
        self.active.clear()


class UnavailableRegistrar:
    """Used when the computer is not Windows. Buttons in the window still work."""

    def register(self, hotkey_id: int, modifiers: int, vk: int) -> tuple[bool, str]:
        return False, "Global keys are only available on Windows."

    def clear(self) -> None:
        return None
