"""The BabySitter window.

A top bar holds the state, the name, the tabs, and privacy. A slim pin
rail stays under it. Closing the window hides it; Quit is in the tray.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from babysitter.paths import data_dir
from babysitter.ui.dialogs import show_copyable
from babysitter.ui.pages.desk import (
    HealthPage,
    HistoryPage,
    MemoryPage,
    ModelsPage,
    SchedulePage,
    ScreenPage,
)
from babysitter.ui.pages.home import HomePage
from babysitter.ui.pages.settings_page import SettingsPage
from babysitter.ui.pages.tools_page import ToolsPage
from babysitter.ui.pages.voice_page import VoicePage
from babysitter.ui.theme import STATE_COLORS
from babysitter.version import __version__


class MainWindow(QMainWindow):
    pin_open = Signal(str)
    expanded_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BabySitter")
        self.resize(1280, 900)
        self.setMinimumSize(760, 220)
        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.topbar = QFrame()
        self.topbar.setObjectName("topbar")
        top = QHBoxLayout(self.topbar)
        top.setContentsMargins(14, 8, 14, 8)
        self.status_chip = QLabel("Off")
        self.status_chip.setToolTip("The same state as the floating orb.")
        brand = QLabel("BabySitter")
        brand.setObjectName("word")
        brand.setToolTip(f"Version {__version__}. The number lives in one file.")
        top.addWidget(self.status_chip)
        top.addWidget(brand)
        self.nav_host = QWidget()
        nav = QHBoxLayout(self.nav_host)
        nav.setContentsMargins(8, 0, 8, 0)
        nav.setSpacing(4)
        self.stack = QStackedWidget()
        self.home = HomePage()
        self.schedule_page = SchedulePage()
        self.voice_page = VoicePage()
        self.tools_page = ToolsPage()
        self.memory_page = MemoryPage()
        self.history_page = HistoryPage()
        self.screen_page = ScreenPage()
        self.health_page = HealthPage()
        self.models_page = ModelsPage()
        self.settings_page = SettingsPage()
        pages: list[tuple[str, QWidget, str]] = [
            ("Home", self.home, "Power, this PC, and what you just heard."),
            ("Schedule", self.schedule_page, "Reminders that stay on this PC."),
            ("Voice", self.voice_page, "How BabySitter sounds, and how it hears you."),
            ("Tools", self.tools_page, "Optional search. Off until you turn it on."),
            ("Memory", self.memory_page, "Facts you agree to remember."),
            ("History", self.history_page, "Past sessions, when there are any."),
            ("Screen", self.screen_page, "Look at the screen only when you ask."),
            ("PC Health", self.health_page, "Read-only checks. No Fix button."),
            ("Models", self.models_page, "One model at a time."),
            ("Settings", self.settings_page, "Startup, keys, games, and your files."),
        ]
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (name, page, tip) in enumerate(pages):
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(name) + 28)
            self.nav_group.addButton(button, index)
            nav.addWidget(button)
            self.stack.addWidget(page)
            if index == 0:
                button.setChecked(True)
        self.nav_group.idClicked.connect(self.stack.setCurrentIndex)
        self.nav_scroll = QScrollArea()
        nav_scroll = self.nav_scroll
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        nav_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_scroll.setWidget(self.nav_host)
        nav_scroll.setMinimumHeight(46)
        top.addWidget(nav_scroll, 1)
        self.privacy_chip = QLabel("Private to this PC")
        self.privacy_chip.setObjectName("hint")
        self.privacy_chip.setToolTip(
            "Usage data is never sent. Social search is the only optional path off this PC, and it is off until you turn it on."
        )
        self.expand_button = QPushButton("Expand")
        self.expand_button.setToolTip("Opens the full window. Compact keeps the power row.")
        top.addWidget(self.privacy_chip)
        top.addWidget(self.expand_button)
        layout.addWidget(self.topbar)

        self.pin_host = QFrame()
        self.pin_host.setObjectName("pinbar")
        pin_row = QHBoxLayout(self.pin_host)
        pin_row.setContentsMargins(14, 6, 14, 6)
        pin_label = QLabel("PINNED")
        pin_label.setObjectName("section")
        pin_row.addWidget(pin_label)
        self.pin_buttons = QWidget()
        self.pin_layout = QHBoxLayout(self.pin_buttons)
        self.pin_layout.setContentsMargins(0, 0, 0, 0)
        pin_row.addWidget(self.pin_buttons, 1)
        layout.addWidget(self.pin_host)
        layout.addWidget(self.stack, 1)
        self._expanded = True

    def set_chip(self, state: str, label: str) -> None:
        color = STATE_COLORS.get(state, STATE_COLORS["error"])
        ink = "#1a1404" if state in {"starting", "on", "listening", "thinking", "speaking"} else "#f7fafc"
        self.status_chip.setText(label)
        self.status_chip.setStyleSheet(
            f"color: {ink}; background: {color}; border-radius: 10px; "
            "padding: 4px 10px; font-weight: 700;"
        )

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.nav_scroll.setVisible(expanded)
        self.pin_host.setVisible(expanded)
        self.home.set_detailed(expanded)
        self.expand_button.setText("Compact" if expanded else "Expand")
        self.expand_button.setToolTip(
            "Shows the power row only." if expanded else "Opens the tabs, the pin rail, and the rest of Home."
        )

    def set_pins(self, pins: list[dict]) -> None:
        while self.pin_layout.count():
            item = self.pin_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not pins:
            empty = QLabel("Nothing pinned.")
            empty.setObjectName("hint")
            self.pin_layout.addWidget(empty)
            self.pin_layout.addStretch(1)
            self.home.set_pins_text("Nothing is pinned yet. Pin a reply from Home. It stays on this PC.")
            return
        lines = []
        for pin in pins[-8:]:
            title = str(pin.get("title") or "Pinned")
            button = QPushButton(title)
            button.setToolTip(str(pin.get("body") or ""))
            pin_id = str(pin.get("id") or "")
            button.clicked.connect(lambda _checked=False, item_id=pin_id: self.pin_open.emit(item_id))
            self.pin_layout.addWidget(button)
            lines.append(f"{title}\n{pin.get('body', '')}")
        self.pin_layout.addStretch(1)
        self.home.set_pins_text("\n\n".join(lines))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        event.ignore()
        self.hide()
        marker = data_dir() / "saw-hide-hint"
        if not marker.exists():
            try:
                marker.write_text("shown\n", encoding="utf-8")
            except OSError:
                return
            show_copyable(
                self,
                "BabySitter is still running",
                "Closing the window hides it in the tray. "
                "Quit is on the tray icon or the orb's right-click menu. "
                "The AI stays in the state you left it until you turn it off.",
            )

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)
