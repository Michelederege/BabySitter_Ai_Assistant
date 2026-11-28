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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QPushButton,
    QScrollArea,
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
    ("talk", "Talk", "mic", "Talk to BabySitter. The reply, and what is up next."),
    ("board", "Board", "pin", "What you pinned, and your goals."),
    ("today", "Today", "calendar", "Reminders, timers, and the one inbox."),
    ("desk", "Desk", "pencil", "Your paper, a look-up, your screen, and your files."),
    ("memory", "Memory", "book", "About me, History, and the Journal."),
    ("settings", "Settings", "sliders", "Everything that can be changed, one section at a time."),
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
    """The page title with its one line under it, kept together."""
    box = QWidget()
    box.setObjectName("flowHost")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    title = QLabel(text)
    title.setObjectName("title")
    layout.addWidget(title)
    if hint:
        line = QLabel(hint)
        line.setObjectName("hint")
        line.setWordWrap(True)
        layout.addWidget(line)
    return [box]


def _card(title: str = "", hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("v3card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    if title:
        label = QLabel(title)
        label.setObjectName("cardHead")
        layout.addWidget(label)
    if hint:
        line = QLabel(hint)
        line.setObjectName("hint")
        line.setWordWrap(True)
        layout.addWidget(line)
    return card, layout


def _today_words() -> str:
    from datetime import date

    day = date.today()
    return day.strftime("%A, %B ") + str(day.day)


def _dot(color: str):
    """The state pill's dot: one small filled circle in the state colour."""
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

    pix = QPixmap(20, 20)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(5, 5, 10, 10)
    painter.end()
    return QIcon(pix)


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
        self.notice_layout.setContentsMargins(0, 0, 0, 0)
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
        from PySide6.QtCore import QSize

        from babysitter.ui.icons import icon

        self.emergency = QPushButton("Stop")
        self.emergency.setObjectName("titleAction")
        self.emergency.setIcon(icon("stop", "#e8ecf4", "#ff8a8a", 18))
        self.emergency.setIconSize(QSize(18, 18))
        self.emergency.setAccessibleName("Emergency stop")
        self.emergency.setToolTip("Emergency stop, the same as Ctrl+Alt+F12. Everything turns off now.")
        self.privacy_chip = QPushButton("Private")
        self.privacy_chip.setObjectName("titleAction")
        self.privacy_chip.setIcon(icon("lock", "#e8ecf4", "#ffffff", 18))
        self.privacy_chip.setIconSize(QSize(18, 18))
        self.privacy_chip.setToolTip(
            "Private to this computer. Usage data is never sent. The optional outside tools are off until you turn them on."
        )
        self.privacy_chip.clicked.connect(self._show_privacy)
        self.bell = QPushButton("")
        self.bell.setObjectName("windowButton")
        self.bell.setIcon(icon("bell", "#c6cddc", "#ffffff", 20))
        self.bell.setIconSize(QSize(20, 20))
        self.bell.setAccessibleName("What just happened")
        self.bell.setToolTip("What just happened: every status line, newest first.")
        self.bell.clicked.connect(self.toggle_drawer)
        self.min_button = QPushButton("")
        self.min_button.setObjectName("windowButton")
        self.min_button.setIcon(icon("minimize", "#c6cddc", "#ffffff", 18))
        self.min_button.setAccessibleName("Minimize to the frog")
        self.min_button.setToolTip("Hides the window without turning the AI off. A click on the frog brings it back.")
        self.min_button.clicked.connect(self.hide)
        self.max_button = QPushButton("")
        self.max_button.setObjectName("windowButton")
        self.max_button.setIcon(icon("maximize", "#c6cddc", "#ffffff", 18))
        self.max_button.setAccessibleName("Maximize or restore")
        self.max_button.setToolTip("Maximize or restore. Double-clicking the title bar does the same.")
        self.max_button.clicked.connect(self.toggle_maximized)
        self.close_button = QPushButton("")
        self.close_button.setIcon(icon("close", "#c6cddc", "#ffffff", 18))
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
    def _nav_button(self, index: int, label: str, icon_name: str, tip: str, bottom: bool):
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QToolButton

        from babysitter.ui.icons import icon

        if bottom:
            button = QToolButton()
            button.setText(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setObjectName("placeBottom")
            button.setIconSize(QSize(20, 20))
        else:
            button = QPushButton(label)
            button.setObjectName("place")
            button.setIconSize(QSize(20, 20))
        button.setIcon(icon(icon_name, "#a3aec5", "#e8ecf4", 20))
        button.setCheckable(True)
        button.setToolTip(tip)
        button.setAccessibleName(label)
        button.setCursor(Qt.PointingHandCursor)
        # "icon" is already a Qt property on buttons, so these use their own names.
        button.setProperty("navLabel", label)
        button.setProperty("navIcon", icon_name)
        return button

    def _build_side_menu(self) -> QFrame:
        menu = QFrame()
        menu.setObjectName("sideMenu")
        layout = QVBoxLayout(menu)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(6)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (_key, label, icon_name, tip) in enumerate(PLACES):
            button = self._nav_button(index, label, icon_name, tip, bottom=False)
            self.nav_group.addButton(button, index)
            if _key == "settings":
                layout.addStretch(1)  # Settings sits at the bottom, apart from the five places
            layout.addWidget(button)
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
        for index, (_key, label, icon_name, tip) in enumerate(PLACES):
            button = self._nav_button(index, label, icon_name, tip, bottom=True)
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
        # Talk: the frog and the reply, with Up next and Pinned beside it when there is room,
        # and the talk bar fixed at the bottom.
        self.talk = QWidget()
        talk = QHBoxLayout(self.talk)
        talk.setContentsMargins(28, 22, 28, 16)
        talk.setSpacing(28)
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
        side.setContentsMargins(0, 6, 0, 0)
        side.setSpacing(10)
        side.addLayout(self._side_head("Up next", "Today", "today"))
        home.countdown.setObjectName("sideRow")
        side.addWidget(home.countdown)
        side.addSpacing(18)
        side.addLayout(self._side_head("Pinned", "Board", "board"))
        self.pinned_rows = QWidget()
        self.pinned_rows_layout = QVBoxLayout(self.pinned_rows)
        self.pinned_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.pinned_rows_layout.setSpacing(0)
        side.addWidget(self.pinned_rows)
        # Kept for anything that reads the plain lines.
        self.pinned_lines = QLabel("Nothing is pinned yet.")
        self.pinned_lines.setObjectName("sideMuted")
        self.pinned_lines.setWordWrap(True)
        side.addWidget(self.pinned_lines)
        side.addStretch(1)
        talk.addWidget(self.talk_side)
        talk_place = QWidget()
        column = QVBoxLayout(talk_place)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(_scroll(self.talk), 1)
        column.addWidget(home.talk_bar)
        self._places["talk"] = talk_place
        self.stack.addWidget(talk_place)

        # Board: the pins, then the goals.
        board = QWidget()
        layout = QVBoxLayout(board)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(22)
        layout.addWidget(home.pin_card)
        layout.addWidget(self.schedule_page.goals_box)
        from babysitter.wishlist import SHEET_HEADER

        # Requests BabySitter can't do yet. The header is the rule he asked for.
        requests = QWidget()
        requests_layout = QVBoxLayout(requests)
        requests_layout.setContentsMargins(0, 0, 0, 0)
        requests_layout.setSpacing(8)
        requests_title = QLabel("Requests")
        requests_title.setObjectName("boardSection")
        requests_hint = QLabel(SHEET_HEADER)
        requests_hint.setObjectName("hint")
        requests_hint.setWordWrap(True)
        requests_layout.addWidget(requests_title)
        requests_layout.addWidget(requests_hint)
        self.requests_list = QListWidget()
        self.requests_list.setObjectName("plainList")
        self.requests_list.setAccessibleName("Requests BabySitter can't do yet")
        self.requests_list.setWordWrap(True)
        self.requests_list.setMinimumHeight(90)
        requests_layout.addWidget(self.requests_list)
        row = QHBoxLayout()
        self.requests_remove = QPushButton("Remove the selected request")
        self.requests_remove.setToolTip("For a request that's been built, or one you no longer want.")
        row.addWidget(self.requests_remove)
        row.addStretch(1)
        requests_layout.addLayout(row)
        layout.addWidget(requests)
        layout.addStretch(1)
        self._place_page("board", board)

        # Today: the agenda and the one inbox, side by side when there is room.
        today = QWidget()
        layout = QVBoxLayout(today)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(22)
        head = QVBoxLayout()
        head.setSpacing(2)
        title = QLabel("Today")
        title.setObjectName("title")
        self.today_date = QLabel(_today_words())
        self.today_date.setObjectName("hint")
        head.addWidget(title)
        head.addWidget(self.today_date)
        layout.addLayout(head)

        # Your briefing: one line and Play it now.
        from PySide6.QtCore import QSize

        from babysitter.ui.icons import pixmap as icon_pixmap

        briefing = QFrame()
        briefing.setObjectName("v3card")
        row = QHBoxLayout(briefing)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(16)
        sun = QLabel()
        sun.setObjectName("briefIcon")
        sun.setPixmap(icon_pixmap("calendar", "#e8ecf4", 20))
        sun.setFixedSize(QSize(40, 40))
        sun.setAlignment(Qt.AlignmentFlag.AlignCenter)
        words = QVBoxLayout()
        words.setSpacing(2)
        brief_title = QLabel("Your briefing")
        brief_title.setObjectName("cardTitle")
        brief_line = QLabel("Your reminders, calendar and anything due, read out in one go. Say \"brief me\" any time.")
        brief_line.setObjectName("cardBody")
        brief_line.setWordWrap(True)
        words.addWidget(brief_title)
        words.addWidget(brief_line)
        play = QPushButton("Play it now")
        play.clicked.connect(lambda: self.home.command_submitted.emit("brief me"))
        row.addWidget(sun)
        row.addLayout(words, 1)
        row.addWidget(play)
        layout.addWidget(briefing)

        grid = WrapGrid(360)
        # Agenda: the heading with its two buttons, the list in one card, one line under it.
        agenda = QWidget()
        agenda.setProperty("noWrap", True)
        agenda_layout = QVBoxLayout(agenda)
        agenda_layout.setContentsMargins(0, 0, 0, 0)
        agenda_layout.setSpacing(12)
        agenda_head = QHBoxLayout()
        agenda_title = QLabel("Agenda")
        agenda_title.setObjectName("boardSection")
        self.add_reminder = QPushButton("Add a reminder")
        timer = QPushButton("10-minute timer")
        timer.clicked.connect(lambda: self.home.command_submitted.emit("set a timer for 10 minutes"))
        agenda_head.addWidget(agenda_title)
        agenda_head.addStretch(1)
        agenda_head.addWidget(self.add_reminder)
        agenda_head.addWidget(timer)
        agenda_layout.addLayout(agenda_head)
        schedule = self.schedule_page
        self.reminder_form = QFrame()
        self.reminder_form.setObjectName("v3card")
        form = QVBoxLayout(self.reminder_form)
        form.setContentsMargins(16, 14, 16, 14)
        form.setSpacing(8)
        form.addWidget(schedule.text)
        form.addWidget(schedule.when)
        buttons = QHBoxLayout()
        buttons.addWidget(schedule.add_button)
        buttons.addWidget(schedule.remove_button)
        buttons.addStretch(1)
        form.addLayout(buttons)
        self.reminder_form.hide()
        self.add_reminder.clicked.connect(self._toggle_reminder_form)
        agenda_layout.addWidget(self.reminder_form)
        list_card = QFrame()
        list_card.setObjectName("listCard")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(18, 8, 18, 8)
        list_layout.addWidget(schedule.list)
        agenda_layout.addWidget(list_card)
        note = QLabel("Reminders speak with the Windows voice even while the AI is off.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        agenda_layout.addWidget(note)
        agenda_layout.addStretch(1)

        # Inbox: the heading with Check now, the list in one card, the read-only line.
        tools = self.tools_page
        inbox = QWidget()
        inbox.setProperty("noWrap", True)
        inbox_layout = QVBoxLayout(inbox)
        inbox_layout.setContentsMargins(0, 0, 0, 0)
        inbox_layout.setSpacing(12)
        inbox_head = QHBoxLayout()
        inbox_title = QLabel("Inbox")
        inbox_title.setObjectName("boardSection")
        tools.refresh_inbox.setText("Check now")
        tools.refresh_inbox.setObjectName("")
        inbox_head.addWidget(inbox_title)
        inbox_head.addStretch(1)
        inbox_head.addWidget(tools.refresh_inbox)
        inbox_layout.addLayout(inbox_head)
        inbox_card = QFrame()
        inbox_card.setObjectName("listCard")
        inbox_card_layout = QVBoxLayout(inbox_card)
        inbox_card_layout.setContentsMargins(18, 8, 18, 8)
        tools.inbox.setObjectName("plainList")
        tools.inbox.setMinimumHeight(0)
        if tools.inbox.count() == 0:
            tools.inbox.addItem("Press Check now, or link an account under Settings, Accounts and home.")
        inbox_card_layout.addWidget(tools.inbox)
        inbox_layout.addWidget(inbox_card)
        read_only = QLabel("Read-only. BabySitter reads these; it never sends, moves or deletes anything.")
        read_only.setObjectName("hint")
        read_only.setWordWrap(True)
        inbox_layout.addWidget(read_only)
        inbox_layout.addStretch(1)
        grid.add(agenda)
        grid.add(inbox)
        layout.addWidget(grid)
        layout.addStretch(1)
        self._place_page("today", today)
        from babysitter.ui.flow import fit_list

        fit_list(tools.inbox, max_rows=10)

        # Desk: help with what you are working on.
        desk = QWidget()
        layout = QVBoxLayout(desk)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(22)
        for widget in _title("Desk", "Help with what you're working on: your paper, your screen, your files."):
            layout.addWidget(widget)
        grid = WrapGrid(360)
        say = self.home.command_submitted.emit

        def buttons(card_layout, pairs) -> None:
            from babysitter.ui.flow import FlowLayout

            host = QWidget()
            host.setObjectName("flowHost")
            flow = FlowLayout(host, spacing=8)
            for label, command in pairs:
                button = QPushButton(label)
                button.clicked.connect(lambda _c=False, command=command: say(command))
                flow.addWidget(button)
            card_layout.addWidget(host)

        paper, paper_layout = _card(
            "Your paper",
            "I only read it when its tab is in front or when you ask about your paper. "
            "Credits only name sources you gave me.",
        )
        buttons(paper_layout, (
            ("What am I writing?", "what am I writing"),
            ("Feedback on my draft", "give me feedback on my draft"),
            ("Check my citations", "check the citations in my paper"),
        ))
        lookup, lookup_layout = _card(
            "Look something up",
            "Asks first every time. Only your search words go to your own search server.",
        )
        search_row = QHBoxLayout()
        self.lookup_box = QLineEdit()
        self.lookup_box.setAccessibleName("Words to look up")
        self.lookup_box.setPlaceholderText("ollama release notes")
        search = QPushButton("Search")

        def look_up() -> None:
            words = " ".join(self.lookup_box.text().split())
            if words:
                say(f"look up {words}")
                self.lookup_box.clear()

        search.clicked.connect(look_up)
        self.lookup_box.returnPressed.connect(look_up)
        search_row.addWidget(self.lookup_box, 1)
        search_row.addWidget(search)
        lookup_layout.addLayout(search_row)
        screen, screen_layout = _card(
            "Your screen",
            "Read-only: I never click or type for you. Pictures stay in memory and aren't saved.",
        )
        buttons(screen_layout, (
            ("Look at my screen", "look at my screen"),
            ("Read the small text", "read the small text on my screen"),
            ("Watch monitor 1", "look at monitor one"),
            ("Watch monitor 2", "look at monitor two"),
            ("Read it out", "read my screen"),
            ("Cite this page", "cite this page"),
            ("Stop watching", "stop watching"),
        ))
        self.screen_page.embed()
        self.screen_page.look_button.hide()
        self.screen_page.body.setMaximumHeight(110)
        screen_layout.addWidget(self.screen_page)
        files, files_layout = _card("Find a file", "Programs are listed but never started.")
        self.files_page.embed()
        files_layout.addWidget(self.files_page)
        for card in (paper, lookup, screen, files):
            grid.add(card)
        layout.addWidget(grid)
        layout.addStretch(1)
        self._place_page("desk", desk)

        # Memory: About me, History, Journal.
        memory = QWidget()
        layout = QVBoxLayout(memory)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(20)
        memory.setProperty("noWrap", True)
        head = QHBoxLayout()
        for widget in _title("Memory", "Kept on this PC and encrypted. Only you can read it."):
            head.addWidget(widget, 1)
        segments = QFrame()
        segments.setObjectName("segmentGroup")
        tabs = QHBoxLayout(segments)
        tabs.setContentsMargins(4, 4, 4, 4)
        tabs.setSpacing(2)
        self.memory_tabs = QButtonGroup(self)
        self.memory_stack = QStackedWidget()
        for page in (self.memory_page, self.history_page, self.journal_page):
            page.embed()
        for index, (label, page) in enumerate(
            (("About me", self.memory_page), ("History", self.history_page), ("Journal", self.journal_page))
        ):
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            self.memory_tabs.addButton(button, index)
            tabs.addWidget(button)
            self.memory_stack.addWidget(page)
        self.memory_tabs.button(0).setChecked(True)
        self.memory_tabs.idClicked.connect(self.memory_stack.setCurrentIndex)
        head.addWidget(segments, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(head)
        layout.addWidget(self.memory_stack, 1)
        self._place_page("memory", memory)

        # Settings: one section at a time, the list on the left or in a row when narrow.
        settings = QWidget()
        self.settings_host = settings
        layout = QVBoxLayout(settings)
        layout.setContentsMargins(28, 22, 28, 12)
        layout.setSpacing(18)
        for widget in _title("Settings", "Everything saves as you change it."):
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

    def _toggle_reminder_form(self) -> None:
        showing = not self.reminder_form.isVisible()
        self.reminder_form.setVisible(showing)
        self.add_reminder.setText("Close" if showing else "Add a reminder")
        if showing:
            self.schedule_page.text.setFocus()

    def _side_head(self, label: str, link: str, place: str) -> QHBoxLayout:
        """"UP NEXT ............ Today": a section label with its page link on the right."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 4)
        title = QLabel(label.upper())
        title.setObjectName("sectionLabel")
        go = QPushButton(link)
        go.setObjectName("sideLink")
        go.setCursor(Qt.PointingHandCursor)
        go.clicked.connect(lambda: self.show_place(place))
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(go)
        return row

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
            parts = [tools.get("accounts"), sections.get("accounts"), tools.get("lookup")]
        elif key == "alerts":
            parts = [sections.get("alerts")]
        elif key == "privacy":
            parts = [sections.get("privacy")]
        elif key == "this_pc":
            parts = [self.home.pc_card, self.health_page, sections.get("this_pc")]
        elif key == "updates":
            parts = [sections.get("updates")]
        for part in parts:
            if part is None:
                continue
            embed = getattr(part, "embed", None)
            if callable(embed):
                embed()
            # The section heading names it already: an inner page title would say it twice.
            for inner in part.findChildren(QLabel, "title"):
                inner.hide()
            # One orange button per screen: inside Settings every button is the quiet grey one.
            for button in part.findChildren(QPushButton, "primary"):
                button.setObjectName("")
                button.style().unpolish(button)
                button.style().polish(button)
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
        self.bell.setText("")
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
        self.bell.setText(str(min(self._unseen, 99)))

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
        self.side_menu.setFixedWidth(196 if wide else 68)
        for button in self.nav_group.buttons():
            button.setText(str(button.property("navLabel")) if wide else "")
        self.brand.setVisible(not narrow)
        self.emergency.setText("Stop" if wide else "")
        self.privacy_chip.setText(self._privacy_word if wide else "")
        self.home.hero.set_window_height(self.height())

    def _reflow_pages(self) -> None:
        roomy = content_class(self.stack.width()) == "roomy"
        self.home.set_compact_talk(self.stack.width() <= 560)
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
    _privacy_word = "Private"

    def show_place(self, key: str) -> None:
        index = [place[0] for place in PLACES].index(key)
        if key == "today":
            self.today_date.setText(_today_words())
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
        self.pill.setIcon(_dot(color))
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
            self._privacy_word = "Asks first"
            self.privacy_chip.setToolTip(
                "Online only when you approve. An outside tool is switched on; words leave this PC only after you confirm them."
            )
        else:
            self._privacy_word = "Private"
            self.privacy_chip.setToolTip(
                "Private to this computer. Usage data is never sent. The optional outside tools are off until you turn them on."
            )
        self.privacy_chip.setText(self._privacy_word if window_class(self.width()) == "wide" else "")

    def set_pins(self, pins: list[dict]) -> None:
        self.home.set_pins(pins)
        count = len(pins)
        self.pins_chip.setText(f"{count} pinned")
        from babysitter.deskstore import pin_kind

        latest = [" ".join(str(pin.get("title") or pin.get("body") or "Note").split())[:60] for pin in pins[-3:]]
        self.pinned_lines.setText("\n".join(f"• {line}" for line in reversed(latest)) or "Nothing is pinned yet.")
        self.pinned_lines.setVisible(not latest)
        while self.pinned_rows_layout.count():
            item = self.pinned_rows_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        recent = list(reversed(pins[-3:]))
        for index, pin in enumerate(recent):
            row = QFrame()
            row.setObjectName("sideRowFrame" if index < len(recent) - 1 else "sideRowLast")
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 12, 0, 12)
            line.setSpacing(12)
            kind = pin_kind(pin)
            tag = QLabel(kind.upper())
            tag.setObjectName(f"tag_{kind}")
            title = QLabel(" ".join(str(pin.get("title") or pin.get("body") or "Note").split())[:60])
            title.setObjectName("sideRow")
            title.setWordWrap(True)
            line.addWidget(tag, 0, Qt.AlignmentFlag.AlignTop)
            line.addWidget(title, 1)
            self.pinned_rows_layout.addWidget(row)

    def set_next(self, text: str) -> None:
        self.next_chip.setText(f"Next · {text}" if text else "Next · nothing counting down")

    def show_notice(self, text: str, action: str, callback) -> None:
        """One notice at a time. A newer one replaces the older; the drawer keeps every line."""
        self.notice_text.setText(text)
        self.notice_action.setText(action)
        self._notice_callback = callback
        self.notice_strip.show()

    def set_requests(self, lines: list[str]) -> None:
        """The numbered request lines (the header is the card's own hint)."""
        from babysitter.ui.flow import fit_list

        self.requests_list.clear()
        for line in lines:
            self.requests_list.addItem(line)
        if not lines:
            self.requests_list.addItem("Nothing saved yet. When I can't do something you ask, it's added here.")
        self.requests_remove.setVisible(bool(lines))
        fit_list(self.requests_list)

    def has_notice(self) -> bool:
        """A notice with a button is showing."""
        return self._notice_callback is not None and not self.notice_strip.isHidden()

    def run_notice(self) -> bool:
        """Press the notice's button, as "fix it" does. False when there is none."""
        if not self.has_notice():
            return False
        self._notice_clicked()
        return True

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
