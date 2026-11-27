"""The BabySitter window, v3: six places in one resizable window.

Talk, Board, Today, Desk, Memory, and Settings replace the twelve pages.
There is no Half screen: the window resizes from any edge, snaps, and
remembers its size, and the layout reflows by width (labels, icons only,
then a bottom bar). The state pill opens the state menu with power,
intelligence, game mode, and the keyword. The bell opens What just
happened. Notices show one strip under the title bar.

The pages that do the work are the same objects as before; this window
only decides where each one sits. Every name the rest of the app uses
(home, schedule_page, settings_page, pill, emergency, set_chip, ...) is
kept, so the features underneath are unchanged.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from babysitter.ui.flow import WrapGrid
from babysitter.ui.frameless import FramelessWindow, content_class, window_class
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
from babysitter.ui.theme import STATE_COLORS, STATE_WORDS
from babysitter.version import __version__

PLACES = (
    ("talk", "Talk", "◉", "Talk to BabySitter. The reply, and what is up next."),
    ("board", "Board", "▦", "What you pinned, and your goals."),
    ("today", "Today", "◷", "Reminders, timers, and the one inbox."),
    ("desk", "Desk", "✎", "Your paper, a look-up, your screen, and your files."),
    ("memory", "Memory", "❖", "About me, History, and the Journal."),
    ("settings", "Settings", "⚙", "Everything that can be changed, one section at a time."),
)

# People and Voice ID is in the design, but Voice ID is not built yet, so
# its section is left out rather than shown with nothing behind it.
SETTINGS_SECTIONS = (
    ("voice", "Voice and hearing"),
    ("brain", "Brain"),
    ("personality", "Personality"),
    ("games", "Games"),
    ("accounts", "Accounts and home"),
    ("alerts", "Alerts and quiet hours"),
    ("privacy", "Privacy and data"),
    ("this_pc", "This PC"),
    ("updates", "Updates and setup"),
)


def _scroll(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(widget)
    return area


def _title(text: str, hint: str = "") -> list[QWidget]:
    title = QLabel(text)
    title.setObjectName("title")
    widgets: list[QWidget] = [title]
    if hint:
        line = QLabel(hint)
        line.setObjectName("hint")
        line.setWordWrap(True)
        widgets.append(line)
    return widgets


def _card(title: str = "", hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("v3card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    if title:
        label = QLabel(title.upper())
        label.setObjectName("sectionLabel")
        layout.addWidget(label)
    if hint:
        line = QLabel(hint)
        line.setObjectName("hint")
        line.setWordWrap(True)
        layout.addWidget(line)
    return card, layout


class _StateMenu(QFrame):
    """Opens from the state pill: power, intelligence, game mode, keyword."""

    def __init__(self, cells: list[QWidget]) -> None:
        super().__init__(None, Qt.Popup)
        self.setObjectName("statePopup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        self.word = QLabel("Off")
        self.word.setObjectName("stateWord")
        self.sentence = QLabel("The AI is off. Nothing is listening.")
        self.sentence.setObjectName("hint")
        self.sentence.setWordWrap(True)
        layout.addWidget(self.word)
        layout.addWidget(self.sentence)
        for cell in cells:
            layout.addWidget(cell)
        keys = QLabel("Ctrl+Alt+F11 on/off · Ctrl+Alt+F12 stop")
        keys.setObjectName("mono")
        layout.addWidget(keys)
        self.setMinimumWidth(340)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)


class MainWindow(FramelessWindow):
    pin_open = Signal(str)
    expanded_changed = Signal(bool)  # kept for the settings file; v3 has no Half screen
    hidden_to_tray = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BabySitter")
        self._expanded = True
        self._unseen = 0

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

        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_titlebar())

        self.notice_host = QWidget()
        self.notice_layout = QVBoxLayout(self.notice_host)
        self.notice_layout.setContentsMargins(14, 8, 14, 0)
        self.notice_layout.setSpacing(8)
        self.notice_layout.addWidget(self.home.version_banner)
        self.notice_layout.addWidget(self.home.tray_banner)
        # v3: one notice at a time, with one action and Later.
        self.notice_strip = QFrame()
        self.notice_strip.setObjectName("noticeStrip")
        strip = QHBoxLayout(self.notice_strip)
        strip.setContentsMargins(12, 8, 12, 8)
        self.notice_text = QLabel("")
        self.notice_text.setWordWrap(True)
        self.notice_action = QPushButton("")
        self.notice_action.setObjectName("primary")
        later = QPushButton("Later")
        later.setObjectName("quiet")
        later.clicked.connect(self.notice_strip.hide)
        strip.addWidget(self.notice_text, 1)
        strip.addWidget(self.notice_action)
        strip.addWidget(later)
        self.notice_strip.hide()
        self._notice_callback = None
        self.notice_action.clicked.connect(self._notice_clicked)
        self.notice_layout.addWidget(self.notice_strip)
        outer.addWidget(self.notice_host)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        self.side_menu = self._build_side_menu()
        middle.addWidget(self.side_menu)
        self.stack = QStackedWidget()
        middle.addWidget(self.stack, 1)
        outer.addLayout(middle, 1)
        self.bottom_bar = self._build_bottom_bar()
        outer.addWidget(self.bottom_bar)

        self._places: dict[str, QWidget] = {}
        self._build_places()
        # Rows of buttons wrap instead of pushing a narrow window sideways.
        from babysitter.ui.flow import wrap_wide_rows

        for page in self._places.values():
            wrap_wide_rows(page)
        self._build_drawer(root)
        self._state_menu = _StateMenu(list(self.home._control_cells))
        self.pill.clicked.connect(self._open_state_menu)
        self.home.pin_open.connect(self.pin_open.emit)
        self.home.recent.textChanged.connect(self._count_unseen)
        self.sizeClassChanged.connect(self.apply_size_class)
        self.apply_size_class(window_class(self.width()))
        self.show_place("talk")

    # ---------- title bar ----------
    def _build_titlebar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("titlebar")
        bar.setFixedHeight(44)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(8)
        self.title_icon = QLabel()
        self.title_icon.setFixedSize(20, 20)
        self.title_icon.setScaledContents(True)
        layout.addWidget(self.title_icon)
        self.brand = QLabel("BabySitter")
        self.brand.setObjectName("appName")
        self.brand.setToolTip(f"Version {__version__}.")
        layout.addWidget(self.brand)
        self.pill = QPushButton("Off")
        self.pill.setObjectName("statePill")
        self.pill.setAccessibleName("AI state: Off")
        self.pill.setToolTip("The state menu: power, Game mode, intelligence, and the keyword.")
        self.pill.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.pill)
        # Kept for anything that reads the plain state word.
        self.title_word = QLabel("Off")
        self.title_word.hide()
        self.title_dot = QLabel("●")
        self.title_dot.hide()
        layout.addStretch(1)
        self.emergency = QPushButton("Stop")
        self.emergency.setObjectName("danger")
        self.emergency.setAccessibleName("Emergency stop")
        self.emergency.setToolTip("Emergency stop, the same as Ctrl+Alt+F12. Everything turns off now.")
        self.privacy_chip = QPushButton("Private to this computer")
        self.privacy_chip.setObjectName("quiet")
        self.privacy_chip.setToolTip(
            "Usage data is never sent. The optional outside tools are off until you turn them on."
        )
        self.privacy_chip.clicked.connect(self._show_privacy)
        self.bell = QPushButton("🔔")
        self.bell.setObjectName("windowButton")
        self.bell.setAccessibleName("What just happened")
        self.bell.setToolTip("What just happened: every status line, newest first.")
        self.bell.clicked.connect(self.toggle_drawer)
        self.min_button = QPushButton("—")
        self.min_button.setObjectName("windowButton")
        self.min_button.setAccessibleName("Minimize to the frog")
        self.min_button.setToolTip("Hides the window without turning the AI off. A click on the frog brings it back.")
        self.min_button.clicked.connect(self.hide)
        self.max_button = QPushButton("□")
        self.max_button.setObjectName("windowButton")
        self.max_button.setAccessibleName("Maximize or restore")
        self.max_button.setToolTip("Maximize or restore. Double-clicking the title bar does the same.")
        self.max_button.clicked.connect(self.toggle_maximized)
        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("closeButton")
        self.close_button.setAccessibleName("Close window and turn AI off")
        self.close_button.setToolTip("Asks first, then turns the AI off and hides the window. BabySitter stays in the tray.")
        self.close_button.clicked.connect(self._ask_close)
        for button in (self.emergency, self.privacy_chip, self.bell, self.min_button, self.max_button, self.close_button):
            button.setFocusPolicy(Qt.TabFocus)
            layout.addWidget(button)
        # The status line lives in the state menu and the drawer.
        self.status_line = QLabel("The AI is off. Nothing is listening.")
        self.status_line.setObjectName("hint")
        self.status_line.setWordWrap(True)
        self.status_line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.set_title_bar(bar)
        return bar

    # ---------- the six places, and the menus that switch them ----------
    def _nav_button(self, index: int, label: str, icon: str, tip: str, bottom: bool) -> QPushButton:
        button = QPushButton(f"{icon}  {label}" if not bottom else f"{icon}\n{label}")
        button.setObjectName("place" if not bottom else "placeBottom")
        button.setCheckable(True)
        button.setToolTip(tip)
        button.setAccessibleName(label)
        button.setCursor(Qt.PointingHandCursor)
        # "icon" is already a Qt property on buttons, so these use their own names.
        button.setProperty("navLabel", label)
        button.setProperty("navIcon", icon)
        return button

    def _build_side_menu(self) -> QFrame:
        menu = QFrame()
        menu.setObjectName("sideMenu")
        layout = QVBoxLayout(menu)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(4)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (_key, label, icon, tip) in enumerate(PLACES):
            button = self._nav_button(index, label, icon, tip, bottom=False)
            self.nav_group.addButton(button, index)
            layout.addWidget(button)
        layout.addStretch(1)
        self.nav_group.idClicked.connect(lambda index: self.show_place(PLACES[index][0]))
        return menu

    def _build_bottom_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("bottomBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        self.bottom_group = QButtonGroup(self)
        self.bottom_group.setExclusive(True)
        for index, (_key, label, icon, tip) in enumerate(PLACES):
            button = self._nav_button(index, label, icon, tip, bottom=True)
            self.bottom_group.addButton(button, index)
            layout.addWidget(button, 1)
        self.bottom_group.idClicked.connect(lambda index: self.show_place(PLACES[index][0]))
        return bar

    def _place_page(self, key: str, body: QWidget) -> None:
        host = _scroll(body)
        self._places[key] = host
        self.stack.addWidget(host)

    def _build_places(self) -> None:
        home = self.home
        # Talk: the frog and the reply, with Up next and Pinned beside it when there is room.
        self.talk = QWidget()
        talk = QHBoxLayout(self.talk)
        talk.setContentsMargins(20, 16, 20, 16)
        talk.setSpacing(16)
        main = QVBoxLayout()
        main.setSpacing(10)
        main.addWidget(home.assistant_card)
        self.talk_chips = QWidget()
        chips = QHBoxLayout(self.talk_chips)
        chips.setContentsMargins(0, 0, 0, 0)
        self.next_chip = QPushButton("Next · nothing counting down")
        self.next_chip.setObjectName("chip")
        self.next_chip.clicked.connect(lambda: self.show_place("today"))
        self.pins_chip = QPushButton("0 pinned")
        self.pins_chip.setObjectName("chip")
        self.pins_chip.clicked.connect(lambda: self.show_place("board"))
        chips.addWidget(self.next_chip)
        chips.addWidget(self.pins_chip)
        chips.addStretch(1)
        main.addWidget(self.talk_chips)
        main.addStretch(1)
        talk.addLayout(main, 1)
        self.talk_side = QWidget()
        self.talk_side.setFixedWidth(272)
        side = QVBoxLayout(self.talk_side)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(14)
        upnext, upnext_layout = _card("Up next")
        upnext_layout.addWidget(home.countdown)
        to_today = QPushButton("Open Today")
        to_today.setObjectName("link")
        to_today.clicked.connect(lambda: self.show_place("today"))
        upnext_layout.addWidget(to_today)
        pinned, pinned_layout = _card("Pinned")
        self.pinned_lines = QLabel("Nothing is pinned yet.")
        self.pinned_lines.setWordWrap(True)
        pinned_layout.addWidget(self.pinned_lines)
        to_board = QPushButton("Open Board")
        to_board.setObjectName("link")
        to_board.clicked.connect(lambda: self.show_place("board"))
        pinned_layout.addWidget(to_board)
        side.addWidget(upnext)
        side.addWidget(pinned)
        side.addStretch(1)
        talk.addWidget(self.talk_side)
        self._place_page("talk", self.talk)

        # Board: the pins, then the goals.
        board = QWidget()
        layout = QVBoxLayout(board)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)
        for widget in _title("Board", "What you pinned. Locked notes stay; an unpinned card can be pinned again."):
            layout.addWidget(widget)
        layout.addWidget(home.pin_card)
        goals, goals_layout = _card("Goals")
        goals_layout.addWidget(self.schedule_page.goals_box)
        layout.addWidget(goals)
        layout.addStretch(1)
        self._place_page("board", board)

        # Today: the agenda and the one inbox, side by side when there is room.
        today = QWidget()
        layout = QVBoxLayout(today)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)
        for widget in _title("Today"):
            layout.addWidget(widget)
        grid = WrapGrid(360)
        agenda, agenda_layout = _card("Agenda", "Reminders and timers. They ring even while the AI is off.")
        agenda_layout.addWidget(self.schedule_page)
        inbox, inbox_layout = _card("Inbox", "Read-only. BabySitter reads these; it never sends, moves or deletes anything.")
        inbox_layout.addWidget(self.tools_page.sections["inbox"])
        grid.add(agenda)
        grid.add(inbox)
        layout.addWidget(grid)
        layout.addStretch(1)
        self._place_page("today", today)

        # Desk: help with what you are working on.
        desk = QWidget()
        layout = QVBoxLayout(desk)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)
        for widget in _title("Desk"):
            layout.addWidget(widget)
        grid = WrapGrid(360)
        paper, paper_layout = _card(
            "Your paper",
            "I only read it when its tab is in front or when you ask about your paper. "
            "Credits only name sources you gave me.",
        )
        row = QHBoxLayout()
        for label, command in (
            ("What am I writing?", "what am I writing"),
            ("Feedback on my draft", "give me feedback on my draft"),
            ("Check my citations", "check the citations in my paper"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _c=False, command=command: self.home.command_submitted.emit(command))
            row.addWidget(button)
        paper_layout.addLayout(row)
        lookup, lookup_layout = _card("Look something up", "It always asks first and shows the exact words before anything leaves this PC.")
        lookup_layout.addWidget(self.tools_page.sections["lookup"])
        screen, screen_layout = _card("Your screen", "Read-only: it never clicks or types.")
        screen_layout.addWidget(self.screen_page)
        files, files_layout = _card("Find a file", "Programs are listed but never started.")
        files_layout.addWidget(self.files_page)
        for card in (paper, lookup, screen, files):
            grid.add(card)
        layout.addWidget(grid)
        layout.addStretch(1)
        self._place_page("desk", desk)

        # Memory: About me, History, Journal.
        memory = QWidget()
        layout = QVBoxLayout(memory)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        for widget in _title("Memory"):
            layout.addWidget(widget)
        tabs = QHBoxLayout()
        self.memory_tabs = QButtonGroup(self)
        self.memory_stack = QStackedWidget()
        for index, (label, page) in enumerate(
            (("About me", self.memory_page), ("History", self.history_page), ("Journal", self.journal_page))
        ):
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            self.memory_tabs.addButton(button, index)
            tabs.addWidget(button)
            self.memory_stack.addWidget(page)
        tabs.addStretch(1)
        self.memory_tabs.button(0).setChecked(True)
        self.memory_tabs.idClicked.connect(self.memory_stack.setCurrentIndex)
        layout.addLayout(tabs)
        layout.addWidget(self.memory_stack, 1)
        self._place_page("memory", memory)

        # Settings: one section at a time, the list on the left or in a row when narrow.
        settings = QWidget()
        self.settings_host = settings
        layout = QVBoxLayout(settings)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        for widget in _title("Settings", "Changes save as soon as you make them."):
            layout.addWidget(widget)
        self.settings_split = QHBoxLayout()
        self.section_list = QListWidget()
        self.section_list.setObjectName("sectionList")
        self.section_list.setAccessibleName("Settings sections")
        self.section_list.setFixedWidth(210)
        self.section_stack = QStackedWidget()
        self._section_keys: list[str] = []
        for key, label in SETTINGS_SECTIONS:
            self.section_list.addItem(label)
            self._section_keys.append(key)
            self.section_stack.addWidget(_scroll(self._settings_section(key, label)))
        self.section_list.currentRowChanged.connect(self.section_stack.setCurrentIndex)
        self.section_list.setCurrentRow(0)
        self.settings_split.addWidget(self.section_list)
        self.settings_split.addWidget(self.section_stack, 1)
        layout.addLayout(self.settings_split, 1)
        self.stack.addWidget(settings)
        self._places["settings"] = settings

        self._page_order = [self.home, self.home.pin_card, self.schedule_page, self.files_page, self.memory_page, self.settings_page]

    def _settings_section(self, key: str, label: str) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 0, 4, 12)
        layout.setSpacing(14)
        heading = QLabel(label)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        sections = self.settings_page.sections
        tools = self.tools_page.sections
        parts: list[QWidget] = []
        if key == "voice":
            parts = [self.voice_page, sections.get("voice")]
        elif key == "brain":
            parts = [sections.get("brain"), self.models_page]
        elif key == "personality":
            parts = [self._personality_box()]
        elif key == "games":
            parts = [sections.get("games")]
        elif key == "accounts":
            parts = [tools.get("accounts"), sections.get("accounts")]
        elif key == "alerts":
            parts = [sections.get("alerts")]
        elif key == "privacy":
            parts = [sections.get("privacy")]
        elif key == "this_pc":
            parts = [self.home.pc_card, self.health_page, sections.get("this_pc")]
        elif key == "updates":
            parts = [sections.get("updates")]
        for part in parts:
            if part is not None:
                layout.addWidget(part)
        layout.addStretch(1)
        return body

    def _personality_box(self) -> QWidget:
        box, layout = _card(
            "A name to answer to",
            "One sentence, saved on this PC and used the next time the AI turns on. "
            "It changes only how I speak: it cannot send mail, change a calendar, or invent a source.",
        )
        row = QHBoxLayout()
        self.persona_name = QLineEdit()
        self.persona_name.setAccessibleName("Persona name")
        self.persona_name.setPlaceholderText("Brook, or EDITH")
        save = QPushButton("Save")
        save.clicked.connect(self._save_persona)
        self.persona_name.returnPressed.connect(self._save_persona)
        plain = QPushButton("Be yourself")
        plain.clicked.connect(lambda: self.home.command_submitted.emit("be yourself"))
        row.addWidget(self.persona_name, 1)
        row.addWidget(save)
        row.addWidget(plain)
        layout.addLayout(row)
        tone = QLabel("Reply length and tone: rate a reply on the Voice and hearing section.")
        tone.setObjectName("hint")
        tone.setWordWrap(True)
        layout.addWidget(tone)
        return box

    def _save_persona(self) -> None:
        name = " ".join(self.persona_name.text().split())
        if name:
            self.home.command_submitted.emit(f"call yourself {name}")
            self.persona_name.clear()

    # ---------- the drawer ----------
    def _build_drawer(self, root: QWidget) -> None:
        self.drawer = QFrame(root)
        self.drawer.setObjectName("drawer")
        layout = QVBoxLayout(self.drawer)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("What just happened")
        title.setObjectName("sectionTitle")
        close = QPushButton("✕")
        close.setObjectName("windowButton")
        close.setAccessibleName("Close What just happened")
        close.clicked.connect(self.toggle_drawer)
        head.addWidget(title, 1)
        head.addWidget(close)
        layout.addLayout(head)
        layout.addWidget(self.status_line)
        layout.addWidget(self.home.log_card, 1)
        self.drawer.hide()

    def toggle_drawer(self) -> None:
        if self.drawer.isVisible():
            self.drawer.hide()
            return
        self._unseen = 0
        self.bell.setText("🔔")
        self._place_drawer()
        self.drawer.show()
        self.drawer.raise_()

    def _place_drawer(self) -> None:
        host = self.centralWidget()
        width = min(380, max(300, host.width() // 3))
        top = 44
        self.drawer.setGeometry(host.width() - width, top, width, max(200, host.height() - top))

    def _count_unseen(self) -> None:
        if self.drawer.isVisible():
            return
        self._unseen += 1
        self.bell.setText(f"🔔 {min(self._unseen, 99)}")

    # ---------- the state menu and the privacy note ----------
    def _open_state_menu(self) -> None:
        self._state_menu.word.setText(self.title_word.text())
        self._state_menu.sentence.setText(self.status_line.text())
        self._state_menu.adjustSize()
        place = self.pill.mapToGlobal(QPoint(0, self.pill.height() + 6))
        self._state_menu.move(place)
        self._state_menu.show()

    def _show_privacy(self) -> None:
        from babysitter.ui.dialogs import show_copyable

        show_copyable(self, "What stays on this PC", self.privacy_chip.toolTip())

    # ---------- reflow ----------
    def apply_size_class(self, cls: str) -> None:
        wide, narrow = cls == "wide", cls == "narrow"
        self.side_menu.setVisible(not narrow)
        self.bottom_bar.setVisible(narrow)
        self.side_menu.setFixedWidth(184 if wide else 64)
        for button in self.nav_group.buttons():
            icon, label = button.property("navIcon"), button.property("navLabel")
            button.setText(f"{icon}  {label}" if wide else str(icon))
        self.brand.setVisible(not narrow)
        self.emergency.setText("Stop" if wide else "■")
        self.privacy_chip.setText(self._privacy_word if wide else "🔒")
        self.home.hero.set_window_height(self.height())

    def _reflow_pages(self) -> None:
        roomy = content_class(self.stack.width()) == "roomy"
        self.talk_side.setVisible(roomy)
        self.talk_chips.setVisible(not roomy)
        narrow_settings = self.stack.width() <= 760
        if narrow_settings:
            self.section_list.setFlow(QListView.Flow.LeftToRight)
            self.section_list.setWrapping(False)
            self.section_list.setFixedWidth(16777215)
            self.section_list.setFixedHeight(44)
            self.settings_split.setDirection(QHBoxLayout.Direction.TopToBottom)
        else:
            self.section_list.setFlow(QListView.Flow.TopToBottom)
            self.section_list.setMinimumHeight(0)
            self.section_list.setMaximumHeight(16777215)
            self.section_list.setFixedWidth(210)
            self.settings_split.setDirection(QHBoxLayout.Direction.LeftToRight)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.home.hero.set_window_height(self.height())
        self._reflow_pages()
        if self.drawer.isVisible():
            self._place_drawer()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not getattr(self, "_wrapped_after_style", False):
            # Sizes are only real once the stylesheet and fonts apply, so
            # rows that looked narrow while building are checked again here.
            self._wrapped_after_style = True
            from babysitter.ui.flow import wrap_wide_rows

            for page in self._places.values():
                wrap_wide_rows(page, threshold=240)
        QTimer.singleShot(0, self._reflow_pages)

    # ---------- what the rest of the app calls ----------
    _privacy_word = "Private to this computer"

    def show_place(self, key: str) -> None:
        index = [place[0] for place in PLACES].index(key)
        self.stack.setCurrentWidget(self._places[key])
        for group in (self.nav_group, self.bottom_group):
            button = group.button(index)
            if button is not None:
                button.setChecked(True)
        self._reflow_pages()

    def show_page(self, page: QWidget) -> None:
        """Open the place, tab, or Settings section that holds this page."""
        places = {
            id(self.home): ("talk", None),
            id(self.home.pin_card): ("board", None),
            id(self.schedule_page): ("today", None),
            id(self.tools_page): ("today", None),
            id(self.files_page): ("desk", None),
            id(self.screen_page): ("desk", None),
            id(self.memory_page): ("memory", 0),
            id(self.history_page): ("memory", 1),
            id(self.journal_page): ("memory", 2),
            id(self.voice_page): ("settings", "voice"),
            id(self.models_page): ("settings", "brain"),
            id(self.health_page): ("settings", "this_pc"),
            id(self.settings_page): ("settings", None),
        }
        found = places.get(id(page))
        if found is None:
            return
        key, inner = found
        self.show_place(key)
        self._current = page
        if key == "memory" and isinstance(inner, int):
            self.memory_tabs.button(inner).setChecked(True)
            self.memory_stack.setCurrentIndex(inner)
        elif key == "settings" and isinstance(inner, str):
            self.section_list.setCurrentRow(self._section_keys.index(inner))

    def current_page(self) -> QWidget | None:
        current = getattr(self, "_current", None)
        index = self.stack.currentIndex()
        keys = [place[0] for place in PLACES]
        key = keys[index] if 0 <= index < len(keys) else "talk"
        mapping = {
            "talk": self.home, "board": self.home.pin_card, "today": self.schedule_page,
            "desk": self.files_page, "memory": self.memory_stack.currentWidget(), "settings": self.settings_page,
        }
        if current is not None and self.show_page_key(current) == key:
            return current
        return mapping.get(key)

    def show_page_key(self, page: QWidget) -> str:
        for key, owners in (
            ("talk", (self.home,)),
            ("board", (self.home.pin_card,)),
            ("today", (self.schedule_page, self.tools_page)),
            ("desk", (self.files_page, self.screen_page)),
            ("memory", (self.memory_page, self.history_page, self.journal_page)),
            ("settings", (self.voice_page, self.models_page, self.health_page, self.settings_page)),
        ):
            if page in owners:
                return key
        return ""

    def set_chip(self, state: str, label: str) -> None:
        color = STATE_COLORS.get(state, STATE_COLORS["error"])
        self.pill.setText(label)
        self.pill.setAccessibleName(f"AI state: {label}")
        self.pill.setStyleSheet(
            f"QPushButton#statePill {{ color: {color}; border: 1px solid {color}; }}"
        )
        word = STATE_WORDS.get(state, label)
        self.title_word.setText(word)
        if self._state_menu.isVisible():
            self._state_menu.word.setText(word)

    def set_status_line(self, text: str) -> None:
        line = " ".join(str(text or "").split())[:200]
        self.status_line.setText(line)
        if self._state_menu.isVisible():
            self._state_menu.sentence.setText(line)

    def set_privacy(self, online_possible: bool) -> None:
        if online_possible:
            self._privacy_word = "Online only when you approve"
            self.privacy_chip.setToolTip(
                "An outside tool is switched on. Words leave this PC only after you confirm them."
            )
        else:
            self._privacy_word = "Private to this computer"
            self.privacy_chip.setToolTip(
                "Usage data is never sent. The optional outside tools are off until you turn them on."
            )
        self.privacy_chip.setText(self._privacy_word if window_class(self.width()) == "wide" else "🔒")

    def set_pins(self, pins: list[dict]) -> None:
        self.home.set_pins(pins)
        count = len(pins)
        self.pins_chip.setText(f"{count} pinned")
        latest = [" ".join(str(pin.get("title") or pin.get("body") or "Note").split())[:60] for pin in pins[-3:]]
        self.pinned_lines.setText("\n".join(f"• {line}" for line in reversed(latest)) or "Nothing is pinned yet.")

    def set_next(self, text: str) -> None:
        self.next_chip.setText(f"Next · {text}" if text else "Next · nothing counting down")

    def show_notice(self, text: str, action: str, callback) -> None:
        """One notice at a time. A newer one replaces the older; the drawer keeps every line."""
        self.notice_text.setText(text)
        self.notice_action.setText(action)
        self._notice_callback = callback
        self.notice_strip.show()

    def _notice_clicked(self) -> None:
        self.notice_strip.hide()
        callback, self._notice_callback = self._notice_callback, None
        if callback is not None:
            callback()

    def show_settings_section(self, key: str) -> None:
        self.show_place("settings")
        if key in self._section_keys:
            self.section_list.setCurrentRow(self._section_keys.index(key))

    def toggle_size(self) -> None:
        self.toggle_maximized()

    def set_expanded(self, expanded: bool) -> None:
        """v2's Half and Full screen. v3 is one resizable window, so this only remembers it."""
        self._expanded = bool(expanded)

    def _ask_close(self) -> None:
        from babysitter.ui.dialogs import ask_yes_no

        if ask_yes_no(
            self,
            "Close the window?",
            "The AI turns off and the window hides. BabySitter stays in the tray, and reminders still ring.",
            "Close and turn the AI off",
            "Keep it open",
        ):
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        event.ignore()
        self.hide()
        self.hidden_to_tray.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key_Escape:
            if self.drawer.isVisible():
                self.drawer.hide()
                return
            focused = self.focusWidget()
            if focused is not None and focused.__class__.__name__ in {"QLineEdit", "QComboBox"}:
                focused.clearFocus()
                return
            self.close()
            return
        if key == Qt.Key_F11 and not mods:
            self.toggle_maximized()
            return
        if key == Qt.Key_L and (mods & Qt.ControlModifier):
            self.show_place("talk")
            self.home.typed.setFocus()
            self.home.typed.selectAll()
            return
        if key in (Qt.Key_PageDown, Qt.Key_PageUp) and (mods & Qt.ControlModifier):
            step = 1 if key == Qt.Key_PageDown else -1
            index = (self.stack.currentIndex() + step) % len(PLACES)
            self.show_place(PLACES[index][0])
            return
        super().keyPressEvent(event)
