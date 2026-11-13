"""The icon that stays in the system tray."""

from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class Tray:
    def __init__(self, icon: QIcon) -> None:
        self.icon = QSystemTrayIcon(icon)
        self.icon.setToolTip("BabySitter — AI is off")
        self.menu = QMenu()
        self.icon.setContextMenu(self.menu)
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        if self.available:
            self.icon.show()

    def set_tooltip(self, text: str) -> None:
        self.icon.setToolTip(text[:120])
