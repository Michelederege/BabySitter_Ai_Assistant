"""Reserves two global keys on Windows: emergency stop, and turn on.

Uses RegisterHotKey, which asks Windows to watch those combinations and
does not install a keyboard hook. Mouse buttons are not handled here.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray


WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", _POINT),
    ]


class WinHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, on_id) -> None:
        super().__init__()
        self.on_id = on_id

    def nativeEventFilter(self, eventType, message):  # noqa: N802
        try:
            kind = bytes(eventType) if not isinstance(eventType, QByteArray) else bytes(eventType)
        except (TypeError, ValueError):
            return False, 0
        if kind != b"windows_generic_MSG":
            return False, 0
        try:
            address = int(message)
            msg = _MSG.from_address(address)
        except (TypeError, ValueError, OSError):
            return False, 0
        if msg.message == WM_HOTKEY:
            self.on_id(int(msg.wParam))
        return False, 0


class WinHotkeyRegistrar:
    def __init__(self) -> None:
        self._ids: list[int] = []
        self._filter: WinHotkeyFilter | None = None
        if sys.platform != "win32":
            raise OSError("Global hotkeys are only installed on Windows.")
        self._user32 = ctypes.windll.user32

    def install_filter(self, app, on_id) -> None:
        self._filter = WinHotkeyFilter(on_id)
        app.installNativeEventFilter(self._filter)

    def register(self, hotkey_id: int, modifiers: int, vk: int) -> tuple[bool, str]:
        ok = self._user32.RegisterHotKey(None, int(hotkey_id), int(modifiers), int(vk))
        if not ok:
            code = ctypes.get_last_error()
            if code == ERROR_HOTKEY_ALREADY_REGISTERED:
                return False, "Another program is already using that key combination."
            return False, f"Windows refused the key (error {code})."
        self._ids.append(int(hotkey_id))
        return True, ""

    def clear(self) -> None:
        for hotkey_id in list(self._ids):
            self._user32.UnregisterHotKey(None, int(hotkey_id))
        self._ids.clear()
