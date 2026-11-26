"""The BabySitter window, v2.

A frameless window with its own title bar (Half screen, Full screen,
Minimize to the orb, Close), a left rail in three groups, a top bar with
the state pill, the latest status line, Emergency stop and the privacy
word, and one shared notice area under the top bar. Only the page
content scrolls. Closing the window hides it and turns the AI off; Quit
is in the tray.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

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
from babysitter.ui.pages.today import FilesPage, JournalPage
from babysitter.ui.pages.tools_page import ToolsPage
from babysitter.ui.pages.voice_page import VoicePage
from babysitter.ui.theme import DARK_INK_STATES, STATE_COLORS, STATE_WORDS
from babysitter.version import __version__


class _TitleBar(QFrame):
    """The custom 40 px title bar. Dragging it moves the window."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self._window = window
        self.setObjectName("titlebar")
        self.setFixedHeight(40)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._window.toggle_size()
        super().mouseDoubleClickEvent(event)


class MainWindow(QMainWindow):
    pin_open = Signal(str)
    expanded_changed = Signal(bool)
    hidden_to_tray = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BabySitter")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.resize(1280, 800)
        self.setMinimumSize(760, 480)
        self._expanded = True

        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_titlebar())

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self._build_rail())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._build_topbar())

        self.notice_host = QWidget()
        self.notice_layout = QVBoxLayout(self.notice_host)
        self.notice_layout.setContentsMargins(14, 8, 14, 0)
        self.notice_layout.setSpacing(8)
        right.addWidget(self.notice_host)

        right.addWidget(self.stack, 1)
        middle.addLayout(right, 1)
        outer.addLayout(middle, 1)

        # The shared notice area holds Home's banners, so every page sees them.
        self.notice_layout.addWidget(self.home.version_banner)
        self.notice_layout.addWidget(self.home.tray_banner)

        self._grip = QSizeGrip(root)
        self._grip.setFixedSize(16, 16)
        self._grip.raise_()

    # ---------- construction ----------
    def _build_titlebar(self) -> QFrame:
        bar = _TitleBar(self)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(8)
        self.title_icon = QLabel()
        self.title_icon.setFixedSize(20, 20)
        self.title_icon.setScaledContents(True)
        layout.addWidget(self.title_icon)
        brand = QLabel("BabySitter")
        brand.setObjectName("appName")
        brand.setToolTip(f"Version {__version__}.")
        layout.addWidget(brand)
        self.title_dot = QLabel("●")
        self.title_word = QLabel("Off")
        self.title_word.setObjectName("hint")
        layout.addWidget(self.title_dot)
        layout.addWidget(self.title_word)
        layout.addStretch(1)
        self.half_button = QPushButton("Half screen")
        self.half_button.setObjectName("windowButton")
        self.half_button.setCheckable(True)
        self.half_button.setAccessibleName("Half screen")
        self.half_button.setToolTip("Snaps to the left half of the screen, leaving room for a game beside it (F11 toggles).")
        self.half_button.clicked.connect(lambda: self._size_clicked(False))
        self.full_button = QPushButton("Full screen")
        self.full_button.setObjectName("windowButton")
        self.full_button.setCheckable(True)
        self.full_button.setAccessibleName("Full screen")
        self.full_button.setToolTip("Fills the screen. The taskbar stays visible (F11 toggles).")
        self.full_button.clicked.connect(lambda: self._size_clicked(True))
        self.min_button = QPushButton("—")
        self.min_button.setObjectName("windowButton")
        self.min_button.setAccessibleName("Minimize to the orb")
        self.min_button.setToolTip("Hides the window without turning the AI off. The frog orb stays, and a click on it brings the window back.")
        self.min_button.clicked.connect(self.hide)
        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("closeButton")
        self.close_button.setAccessibleName("Close window and turn AI off")
        self.close_button.setToolTip("Turns the AI off and hides the window (Esc). BabySitter stays in the tray; Quit is there.")
        self.close_button.clicked.connect(self.close)
        for button in (self.half_button, self.full_button, self.min_button, self.close_button):
            button.setFocusPolicy(Qt.TabFocus)
            layout.addWidget(button)
        return bar

    def _build_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(148)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)

        self.stack = QStackedWidget()
        self.home = HomePage()
        self.schedule_page = SchedulePage()
        self.journal_page = JournalPage()
        self.files_page = FilesPage()
        self.voice_page = VoicePage()
        self.memory_page = MemoryPage()
        self.history_page = HistoryPage()
        self.screen_page = ScreenPage()
        self.tools_page = ToolsPage()
        self.health_page = HealthPage()
        self.models_page = ModelsPage()
        self.settings_page = SettingsPage()

        groups: list[tuple[str, list[tuple[str, QWidget, str]]]] = [
            (
                "TODAY",
                [
                    ("Home", self.home, "Power, the assistant, this PC, and what just happened."),
                    ("Reminders", self.schedule_page, "Reminders and goals that stay on this PC."),
                    ("Journal", self.journal_page, "Program names and minutes, on this PC, for 90 days."),
                    ("Files", self.files_page, "Find a file by a few words. Programs are never started."),
                ],
            ),
            (
                "ASSISTANT",
                [
                    ("Voice", self.voice_page, "How BabySitter sounds, and how it hears you."),
                    ("Memory", self.memory_page, "Facts saved on this PC."),
                    ("History", self.history_page, "Past conversations, when there are any."),
                    ("Screen", self.screen_page, "Look at the screen only when you ask."),
                    ("Tools", self.tools_page, "Google and search. All off until you turn them on."),
                ],
            ),
            (
                "THIS PC",
                [
                    ("PC Health", self.health_page, "Read-only checks. Suggestions wait for a yes."),
                    ("Models", self.models_page, "One model at a time."),
                    ("Settings", self.settings_page, "Startup, keys, games, and your files."),
                ],
            ),
        ]

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        index = 0
        for group_name, pages in groups:
            label = QLabel(group_name)
            label.setObjectName("railGroup")
            layout.addWidget(label)
            for name, page, tip in pages:
                button = QPushButton(name)
                button.setObjectName("nav")
                button.setCheckable(True)
                button.setToolTip(tip)
                button.setCursor(Qt.PointingHandCursor)
                self.nav_group.addButton(button, index)
                layout.addWidget(button)
                host = self._scrolling(page)
                self.stack.addWidget(host)
                if index == 0:
                    button.setChecked(True)
                index += 1
        self.nav_group.idClicked.connect(self.stack.setCurrentIndex)
        layout.addStretch(1)

        self._page_order = [page for _name, pages in groups for _label, page, _tip in pages]
        self.home.pin_open.connect(self.pin_open.emit)
        return rail

    def _scrolling(self, page: QWidget) -> QWidget:
        if isinstance(page, ToolsPage):
            return page  # Tools brings its own scroll area.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)
        self.pill = QPushButton("Off")
        self.pill.setAccessibleName("AI state: Off")
        self.pill.setToolTip("The same power switch as everywhere else. While Working, it cancels.")
        self.pill.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.pill)
        self.status_line = QLabel("The AI is off. Nothing is listening.")
        self.status_line.setObjectName("hint")
        self.status_line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status_line, 1)
        self.emergency = QPushButton("Emergency stop")
        self.emergency.setAccessibleName("Emergency stop")
        self.emergency.setObjectName("danger")
        self.emergency.setToolTip("The same as Ctrl+Alt+F12. Turns the AI fully off, even when the window is hidden.")
        layout.addWidget(self.emergency)
        self.privacy_chip = QLabel("Private to this computer")
        self.privacy_chip.setObjectName("hint")
        self.privacy_chip.setToolTip(
            "Usage data is never sent. The optional outside tools are off until you turn them on."
        )
        layout.addWidget(self.privacy_chip)
        return bar

    # ---------- behavior ----------
    def current_page(self) -> QWidget | None:
        index = self.stack.currentIndex()
        if 0 <= index < len(self._page_order):
            return self._page_order[index]
        return None

    def show_page(self, page: QWidget) -> None:
        try:
            index = self._page_order.index(page)
        except ValueError:
            return
        self.stack.setCurrentIndex(index)
        button = self.nav_group.button(index)
        if button is not None:
            button.setChecked(True)

    def set_chip(self, state: str, label: str) -> None:
        color = STATE_COLORS.get(state, STATE_COLORS["error"])
        ink = "#1a1404" if state in DARK_INK_STATES else "#1a2136"
        if state in {"off", "error", "game"}:
            ink = "#1a2136"
        self.pill.setText(label)
        self.pill.setAccessibleName(f"AI state: {label}")
        self.pill.setStyleSheet(
            f"color: {ink}; background: {color}; border: none; border-radius: 13px; "
            "padding: 5px 14px; font-weight: 700;"
        )
        self.title_dot.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.title_word.setText(STATE_WORDS.get(state, label))

    def set_status_line(self, text: str) -> None:
        self.status_line.setText(" ".join(str(text or "").split())[:200])

    def set_privacy(self, online_possible: bool) -> None:
        if online_possible:
            self.privacy_chip.setText("Online only when you approve")
            self.privacy_chip.setToolTip(
                "An outside tool is switched on. Words leave this PC only after you confirm them."
            )
        else:
            self.privacy_chip.setText("Private to this computer")
            self.privacy_chip.setToolTip(
                "Usage data is never sent. The optional outside tools are off until you turn them on."
            )

    def toggle_size(self) -> None:
        self._size_clicked(not self._expanded)

    def _size_clicked(self, expanded: bool) -> None:
        self.set_expanded(expanded)
        self.expanded_changed.emit(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.half_button.setChecked(not expanded)
        self.full_button.setChecked(expanded)
        self.home.set_detailed(expanded)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        if expanded:
            self.setGeometry(area)
        else:
            self.setGeometry(area.x(), area.y(), max(self.minimumWidth(), area.width() // 2), area.height())

    def set_pins(self, pins: list[dict]) -> None:
        self.home.set_pins(pins)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        event.ignore()
        self.hide()
        self.hidden_to_tray.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key_Escape:
            focused = self.focusWidget()
            if focused is not None and focused.__class__.__name__ in {"QLineEdit", "QComboBox"}:
                focused.clearFocus()
                return
            self.close()
            return
        if key == Qt.Key_F11 and not mods:
            self.toggle_size()
            return
        if key == Qt.Key_L and (mods & Qt.ControlModifier):
            self.show_page(self.home)
            self.home.typed.setFocus()
            self.home.typed.selectAll()
            return
        if key in (Qt.Key_PageDown, Qt.Key_PageUp) and (mods & Qt.ControlModifier):
            count = len(self._page_order)
            if count:
                step = 1 if key == Qt.Key_PageDown else -1
                next_index = (self.stack.currentIndex() + step) % count
                self.show_page(self._page_order[next_index])
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        grip = getattr(self, "_grip", None)
        if grip is not None:
            host = self.centralWidget()
            grip.move(host.width() - grip.width(), host.height() - grip.height())
            grip.raise_()
