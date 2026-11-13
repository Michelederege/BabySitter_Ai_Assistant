"""The full window. Closing it hides it; the orb and the tray stay."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from babysitter.ui.pages.home import HomePage
from babysitter.ui.pages.settings_page import SettingsPage
from babysitter.ui.pages.soon import SoonPage
from babysitter.ui.pages.tools_page import ToolsPage
from babysitter.version import __version__


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BabySitter")
        self.resize(1080, 740)
        self.setMinimumSize(920, 640)
        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(196)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 16, 12, 16)
        brand = QLabel("BabySitter")
        brand.setObjectName("title")
        brand.setToolTip("Your voice assistant. Phase 1 is the power switch.")
        mark = QLabel("BS")
        mark.setToolTip("Placeholder icon. Your own design can replace it later.")
        mark.setStyleSheet(
            "background: #132924; color: #2dd4bf; border-radius: 10px; "
            "font-weight: 700; padding: 6px 8px; font-size: 16px;"
        )
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(44, 36)
        side.addWidget(mark)
        side.addWidget(brand)
        self.status_chip = QLabel("OFF")
        self.status_chip.setToolTip("The same state as the floating orb.")
        side.addWidget(self.status_chip)

        self.stack = QStackedWidget()
        self.home = HomePage()
        self.settings_page = SettingsPage()
        self.tools_page = ToolsPage()
        pages: list[tuple[str, QWidget, str]] = [
            ("Home", self.home, "Power, game mode, and live status."),
            ("History", SoonPage("History", "Phase 6", "Past sessions will be listed here as readable transcripts. You will be able to search, export, or delete them."), "Not built yet."),
            ("Memory", SoonPage("Memory", "Phase 4", "Facts you agree to remember will be listed here. Nothing from a conversation is saved yet."), "Not built yet."),
            ("Tools", self.tools_page, "Optional public social search. Off until you turn it on."),
            ("Voice", SoonPage("Voice", "Phase 2", "Microphone, speech-to-text, and voices will be set up here. The microphone is closed in this phase. Voice cloning will not be added."), "Not built yet."),
            ("Screen", SoonPage("Screen", "Phase 5", "Looking at your screen will be something you start yourself. Nothing is captured on its own, and screenshots are not saved to disk."), "Not built yet."),
            ("PC Health", SoonPage("PC Health", "Phase 5", "Read-only checks of memory, startup programs, and RAM speed will be here. BabySitter will not change the PC for you."), "Not built yet."),
            ("Models", SoonPage("Models", "Phase 7", "Recommended, one at a time: qwen3.5:9b (main), gemma4:12b (writing and coding), qwen3-vl:8b (screenshots). Downloading and removing models from this tab comes later."), "Not built yet."),
            ("Settings", self.settings_page, "Startup, keys, games, and where your files live."),
        ]
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (name, page, tip) in enumerate(pages):
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setCursor(Qt.PointingHandCursor)
            self.nav_group.addButton(button, index)
            side.addWidget(button)
            self.stack.addWidget(page)
            if index == 0:
                button.setChecked(True)
        self.nav_group.idClicked.connect(self.stack.setCurrentIndex)
        side.addStretch(1)
        version = QLabel(f"v{__version__}")
        version.setObjectName("section")
        version.setWordWrap(True)
        version.setToolTip("The version lives in one file: src/babysitter/version.py.")
        side.addWidget(version)
        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)

    def set_chip(self, state: str, label: str) -> None:
        colors = {
            "off": "#8b939e",
            "starting": "#e6b325",
            "on": "#3ddc86",
            "game": "#7aa2ff",
            "error": "#ff5d5d",
        }
        color = colors.get(state, "#ff5d5d")
        self.status_chip.setText(label)
        self.status_chip.setStyleSheet(
            f"color: #0c0e12; background: {color}; border-radius: 8px; "
            "padding: 4px 8px; font-weight: 700;"
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        event.ignore()
        self.hide()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)
