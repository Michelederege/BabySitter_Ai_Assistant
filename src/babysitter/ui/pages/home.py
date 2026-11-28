"""Home, v2: the controls strip, the pinboard and the assistant, then
this PC and what just happened.

The order is fixed: controls first, the assistant beside the pinboard,
readings and the feed last. In half screen everything stacks into one
column, assistant first.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from babysitter.intelligence import MODES
from babysitter.ollama import classify_ollama_process
from babysitter.paths import asset_path
from babysitter.status import format_bytes, format_mib
from babysitter.ui.hero_banner import HeroBanner
from babysitter.ui.orb import _animations_wanted
from babysitter.ui.theme import STATE_COLORS, STATE_WORDS
from babysitter.ui.widgets import BarChart, PowerButton, Sparkline

MAX_PINS = 12

CLICK_HINT = {
    "off": "Click to turn the AI on.",
    "starting": "Starting. Click to cancel.",
    "on": "Click to turn the AI off.",
    "game": "Click to turn the AI fully off.",
    "error": "Click to make sure everything is off.",
}


def _friendly_when(stamp: str) -> str:
    """"2026-11-27T14:05" as "Today 2:05 PM", "Yesterday", "Mon", or "Nov 3"."""
    from datetime import date, datetime

    if not stamp:
        return ""
    try:
        moment = datetime.fromisoformat(stamp[:19])
    except ValueError:
        return stamp[:16].replace("T", " ")
    days = (date.today() - moment.date()).days
    if days == 0:
        return "Today " + moment.strftime("%I:%M %p").lstrip("0")
    if days == 1:
        return "Yesterday"
    if 1 < days < 7:
        return moment.strftime("%a")
    return moment.strftime("%b ") + str(moment.day)


class HomePage(QWidget):
    hold_pressed = Signal()
    hold_released = Signal()
    command_submitted = Signal(str)
    send_heard = Signal()
    pin_reply = Signal()
    pin_note = Signal(str, str)
    copy_reply = Signal()
    copy_log = Signal()
    choose_hero = Signal()
    pin_open = Signal(str)
    pin_unpin = Signal(str)
    fresh_start = Signal()
    pin_lock = Signal(str, bool)
    pin_restore = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 18)
        root.setSpacing(12)

        # Banners live here but are shown in the window's shared notice area.
        self.version_banner = self._banner("dangerBanner")
        self.tray_banner = self._banner("banner")
        self.tray_button = QPushButton("Close the Ollama tray app")
        self.tray_button.setToolTip(
            "Quits Ollama's own tray program so it cannot load a model by itself."
        )
        self.tray_banner.layout().addWidget(self.tray_button)
        self.version_banner.hide()
        self.tray_banner.hide()

        root.addWidget(self._controls_strip())
        self.countdown = QLabel("No reminder is counting down.")
        self.countdown.setObjectName("word")
        self.countdown.setWordWrap(True)
        self.countdown.setToolTip("Time left until the next reminder. It keeps counting while the AI is off.")
        root.addWidget(self.countdown)

        self.detail_host = QWidget()
        self._grid = QGridLayout(self.detail_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)
        self.pin_card = self._pin_card()
        self.assistant_card = self._assistant_card()
        self.pc_card = self._pc_card()
        self.log_card = self._log_card()
        root.addWidget(self.detail_host, 1)
        root.addStretch(0)

        self._vram_samples: list[float] = []
        self._ram_samples: list[float] = []
        self._expanded = True
        self._side_by_side = True
        self._controls_columns = 0
        self._arrange()
        self._place_controls(4)

    # ---------- layout ----------
    def set_countdown(self, text: str) -> None:
        self.countdown.setText(text or "No reminder is counting down.")

    def set_detailed(self, expanded: bool) -> None:
        self._expanded = expanded
        self.hero.set_compact(not expanded)
        self._fit_to_width()

    def _available_width(self) -> int:
        parent = self.parentWidget()
        if parent is not None and parent.width() > 80:
            return parent.width()
        return self.width()

    def _fit_to_width(self) -> None:
        """Keep every control inside the window.

        One row of four cells is wider than a half screen, which used to
        slice the keyword control off the right edge. Narrow windows drop
        to two columns, and the cards stack the same way Half screen does.
        """
        width = self._available_width()
        if width < 80:
            return
        columns = 4 if width >= 980 else 2 if width >= 520 else 1
        changed = columns != self._controls_columns
        self._place_controls(columns)
        side_by_side = self._expanded and width >= 980
        if side_by_side != self._side_by_side:
            self._side_by_side = side_by_side
            self._arrange()
            changed = True
        if changed:
            self.updateGeometry()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_to_width()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._fit_to_width()
        QTimer.singleShot(0, self._fit_to_width)

    def _arrange(self) -> None:
        for card in (self.pin_card, self.assistant_card, self.pc_card, self.log_card):
            self._grid.removeWidget(card)
        if self._side_by_side:
            self._grid.addWidget(self.pin_card, 0, 0)
            self._grid.addWidget(self.assistant_card, 0, 1)
            self._grid.addWidget(self.pc_card, 1, 0)
            self._grid.addWidget(self.log_card, 1, 1)
            self._grid.setColumnStretch(0, 4)
            self._grid.setColumnStretch(1, 6)
        else:
            self._grid.addWidget(self.assistant_card, 0, 0, 1, 2)
            self._grid.addWidget(self.pin_card, 1, 0, 1, 2)
            self._grid.addWidget(self.pc_card, 2, 0, 1, 2)
            self._grid.addWidget(self.log_card, 3, 0, 1, 2)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 1)

    # ---------- the controls strip ----------
    def _controls_strip(self) -> QFrame:
        strip = self._card()
        self._controls_grid = QGridLayout(strip)
        self._controls_grid.setContentsMargins(14, 12, 14, 12)
        self._controls_grid.setSpacing(18)
        self._control_cells = [
            self._power_cell(),
            self._intel_cell(),
            self._game_cell(),
            self._keyword_cell(),
        ]
        return strip

    def _place_controls(self, columns: int) -> None:
        if columns == self._controls_columns:
            return
        self._controls_columns = columns
        for cell in self._control_cells:
            self._controls_grid.removeWidget(cell)
        for index, cell in enumerate(self._control_cells):
            self._controls_grid.addWidget(cell, index // columns, index % columns)
        for column in range(4):
            self._controls_grid.setColumnStretch(column, 1 if column < columns else 0)

    def _power_cell(self) -> QWidget:
        cell = QWidget()
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._section("AI POWER"))
        inner = QHBoxLayout()
        self.power = PowerButton()
        words = QVBoxLayout()
        self.power_word = QLabel("Off")
        self.power_word.setObjectName("word")
        self.power_hint = QLabel(CLICK_HINT["off"])
        self.power_hint.setObjectName("hint")
        self.power_hint.setWordWrap(True)
        words.addWidget(self.power_word)
        words.addWidget(self.power_hint)
        inner.addWidget(self.power)
        inner.addLayout(words, 1)
        layout.addLayout(inner)
        self.try_again = QPushButton("Try turning on")
        self.try_again.setToolTip("Tries to start Ollama and load the model again.")
        self.try_again.hide()
        layout.addWidget(self.try_again)
        layout.addStretch(1)
        return cell

    def _intel_cell(self) -> QWidget:
        cell = QWidget()
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._section("INTELLIGENCE"))
        row = QHBoxLayout()
        row.setSpacing(4)
        self.intel_buttons: dict[str, QPushButton] = {}
        for mode_id in ("low", "medium", "high"):
            button = QPushButton(MODES[mode_id].label)
            button.setObjectName("choice")
            button.setCheckable(True)
            button.setToolTip(MODES[mode_id].summary)
            row.addWidget(button, 1)
            self.intel_buttons[mode_id] = button
        self.intel_buttons["medium"].setChecked(True)
        layout.addLayout(row)
        self.intel_summary = QLabel(MODES["medium"].summary)
        self.intel_summary.setWordWrap(True)
        self.intel_summary.setObjectName("hint")
        layout.addWidget(self.intel_summary)
        self.reload = QPushButton("Reload the model with this setting")
        self.reload.setObjectName("primary")
        self.reload.setToolTip("Unloads the current model, then loads the one for this level.")
        self.reload.hide()
        layout.addWidget(self.reload)
        layout.addStretch(1)
        return cell

    def _game_cell(self) -> QWidget:
        cell = QWidget()
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._section("GAME MODE"))
        row = QHBoxLayout()
        self.game_word = QLabel("Off")
        self.game_word.setObjectName("word")
        self.game = QPushButton("Game mode")
        self.game.setCheckable(True)
        self.game.setObjectName("choice")
        self.game.setToolTip(
            "Unloads the model so a game can use the graphics card. "
            "The microphone stays closed. Ollama stays running with nothing loaded."
        )
        row.addWidget(self.game_word)
        row.addStretch(1)
        row.addWidget(self.game)
        layout.addLayout(row)
        self.game_note = QLabel("Click Game mode to unload the model yourself.")
        self.game_note.setObjectName("hint")
        self.game_note.setWordWrap(True)
        layout.addWidget(self.game_note)
        layout.addStretch(1)
        return cell

    def _keyword_cell(self) -> QWidget:
        cell = QWidget()
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._section("KEYWORD"))
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setAccessibleName("Wake keyword")
        self.keyword_edit.setPlaceholderText("baby sitter")
        self.keyword_edit.setToolTip("The words you say first. Two or three words work best.")
        layout.addWidget(self.keyword_edit)
        self.keyword_button = QPushButton("Listen for a keyword")
        self.keyword_button.setCheckable(True)
        self.keyword_button.setObjectName("primary")
        self.keyword_button.setToolTip(
            "While this is on and the AI is on, the microphone stays open for the keyword. "
            "The sound is checked on this PC. It is not saved and it is not sent."
        )
        layout.addWidget(self.keyword_button)
        keyword_hint = QLabel("The first time asks before a small download.")
        keyword_hint.setObjectName("hint")
        keyword_hint.setWordWrap(True)
        layout.addWidget(keyword_hint)
        layout.addStretch(1)
        return cell

    # ---------- the pinboard ----------
    def _pin_card(self) -> QWidget:
        """v3 Board: the title and count, the filters and Add a note, then the cards in a grid."""
        card = QWidget()
        card.setObjectName("boardBody")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        header = QHBoxLayout()
        header.setSpacing(12)
        words = QVBoxLayout()
        words.setSpacing(2)
        heading = QLabel("Board")
        heading.setObjectName("title")
        self.pin_count = QLabel(f"What you pinned. 0 of {MAX_PINS}.")
        self.pin_count.setObjectName("hint")
        words.addWidget(heading)
        words.addWidget(self.pin_count)
        header.addLayout(words, 1)
        segments = QFrame()
        segments.setObjectName("segmentGroup")
        filters = QHBoxLayout(segments)
        filters.setContentsMargins(4, 4, 4, 4)
        filters.setSpacing(2)
        self._filter = "all"
        self.filter_buttons: dict[str, QPushButton] = {}
        for key, label in (("all", "All"), ("list", "Lists"), ("reply", "Replies"), ("note", "Notes")):
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setChecked(key == "all")
            button.clicked.connect(lambda _c=False, key=key: self._set_filter(key))
            self.filter_buttons[key] = button
            filters.addWidget(button)
        header.addWidget(segments, 0, Qt.AlignmentFlag.AlignVCenter)
        self.add_note = QPushButton("Add a note")
        self.add_note.setObjectName("boardAdd")
        self.add_note.setCursor(Qt.PointingHandCursor)
        self.add_note.setToolTip("Write a note to pin. It stays on this PC.")
        header.addWidget(self.add_note, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)

        # The note form opens only from Add a note.
        self.note_form = QFrame()
        self.note_form.setObjectName("v3card")
        form = QVBoxLayout(self.note_form)
        form.setContentsMargins(16, 14, 16, 14)
        form.setSpacing(8)
        self.pin_title = QLineEdit()
        self.pin_title.setAccessibleName("Pin title")
        self.pin_title.setPlaceholderText("Title")
        self.pin_title.setToolTip("A short name for the card. It stays on this PC.")
        self.pin_body = QLineEdit()
        self.pin_body.setAccessibleName("Pin note")
        self.pin_body.setPlaceholderText("The note to pin")
        self.pin_body.setToolTip("The words on the card. Nothing here is sent.")
        submit = QPushButton("Pin it")
        submit.setObjectName("primary")
        submit.setToolTip("Puts this note on the board. It does not ask the model.")
        submit.clicked.connect(self._submit_pin)
        self.pin_body.returnPressed.connect(self._submit_pin)
        form.addWidget(self.pin_title)
        form.addWidget(self.pin_body)
        form.addWidget(submit, 0, Qt.AlignmentFlag.AlignLeft)
        self.note_form.hide()
        self.add_note.clicked.connect(self._toggle_note_form)
        layout.addWidget(self.note_form)
        # Unpin shows this for ten seconds, with Undo.
        self.undo_strip = QFrame()
        self.undo_strip.setObjectName("banner")
        undo_row = QHBoxLayout(self.undo_strip)
        undo_row.setContentsMargins(10, 6, 10, 6)
        self.undo_label = QLabel("")
        undo = QPushButton("Undo")
        undo.clicked.connect(self._undo_unpin)
        undo_row.addWidget(self.undo_label, 1)
        undo_row.addWidget(undo)
        self.undo_strip.hide()
        layout.addWidget(self.undo_strip)
        self._last_unpinned: dict | None = None
        self._undo_timer = QTimer(self)
        self._undo_timer.setSingleShot(True)
        self._undo_timer.timeout.connect(self._forget_unpin)
        from babysitter.ui.flow import WrapGrid

        self.pin_grid = WrapGrid(250)
        layout.addWidget(self.pin_grid)
        self._all_pins: list[dict] = []
        layout.addStretch(1)
        self.pins = QLabel("Nothing is pinned yet. Add a note, or say 'pin that' after a reply.")
        self.pins.setWordWrap(True)
        self.pins.setObjectName("hint")
        self.pins.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.pins)
        return card

    def _toggle_note_form(self) -> None:
        showing = not self.note_form.isVisible()
        self.note_form.setVisible(showing)
        self.add_note.setText("Close" if showing else "Add a note")
        if showing:
            self.pin_title.setFocus()

    def _submit_pin(self) -> None:
        title = self.pin_title.text().strip()
        body = self.pin_body.text().strip()
        if not title and not body:
            return
        self.pin_note.emit(title or body[:80], body or title)
        self.pin_title.clear()
        self.pin_body.clear()

    def _set_filter(self, key: str) -> None:
        self._filter = key
        for name, button in self.filter_buttons.items():
            button.setChecked(name == key)
        self.set_pins(self._all_pins)

    def show_unpinned(self, pin: dict) -> None:
        self._last_unpinned = dict(pin)
        title = str(pin.get("title") or "The card")
        self.undo_label.setText(f"Unpinned {title[:60]}.")
        self.undo_strip.show()
        self._undo_timer.start(10_000)

    def _undo_unpin(self) -> None:
        if self._last_unpinned is not None:
            self.pin_restore.emit(self._last_unpinned)
        self._forget_unpin()

    def _forget_unpin(self) -> None:
        self._last_unpinned = None
        self.undo_strip.hide()

    def set_pins(self, pins: list[dict]) -> None:
        from babysitter.deskstore import pin_kind

        self._all_pins = list(pins)
        self.pin_grid.clear()
        shown = [pin for pin in pins[-MAX_PINS:] if self._filter == "all" or pin_kind(pin) == self._filter]
        self.pin_count.setText(f"What you pinned. {len(pins[-MAX_PINS:])} of {MAX_PINS}.")
        if not shown and pins and self._filter != "all":
            self.pins.setText("Nothing pinned of that kind.")
            self.pins.show()
            return
        if not shown:
            self.pins.setText("Nothing is pinned yet. Add a note, or say 'pin that' after a reply.")
            self.pins.show()
            return
        if len(pins) >= MAX_PINS:
            self.pins.setText("The board is full. Unpin a card before pinning another.")
            self.pins.show()
        else:
            self.pins.hide()
        for pin in shown:
            self.pin_grid.add(self._pin_item(pin))

    def _pin_item(self, pin: dict) -> QFrame:
        frame = QFrame()
        frame.setObjectName("pinCard")
        frame.setMinimumHeight(190)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(8)
        from babysitter.deskstore import pin_kind

        title = str(pin.get("title") or "Pinned")
        body = str(pin.get("body") or "")
        pin_id = str(pin.get("id") or "")
        locked = str(pin.get("locked") or "") == "yes"
        top = QHBoxLayout()
        tag = QLabel(pin_kind(pin).upper())
        tag.setObjectName(f"tag_{pin_kind(pin)}")
        top.addWidget(tag)
        when = _friendly_when(str(pin.get("pinned") or ""))
        if when:
            stamp = QLabel(when)
            stamp.setObjectName("cardWhen")
            top.addWidget(stamp)
        top.addStretch(1)
        if locked:
            from babysitter.ui.icons import pixmap as icon_pixmap

            padlock = QLabel()
            padlock.setPixmap(icon_pixmap("lock", "#a3aec5", 14))
            padlock.setToolTip("Locked: it stays until you unlock it.")
            top.addWidget(padlock)
        layout.addLayout(top)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        title_label.setWordWrap(True)
        title_label.setToolTip(body)
        layout.addWidget(title_label)
        if body and body != title:
            preview = QLabel(body if len(body) <= 160 else body[:157] + "…")
            preview.setObjectName("cardBody")
            preview.setWordWrap(True)
            layout.addWidget(preview)
        layout.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(18)
        copy = QPushButton("Copy")
        copy.setObjectName("textButton")
        copy.setToolTip("Copies the title and the note.")
        copy.clicked.connect(lambda _c=False, text=f"{title}\n{body}".strip(): QApplication.clipboard().setText(text))
        open_button = QPushButton("Open")
        open_button.setObjectName("textButton")
        open_button.setToolTip("Shows the whole card so you can copy it.")
        open_button.clicked.connect(lambda _c=False, item=pin_id: self.pin_open.emit(item))
        lock = QPushButton("Unlock" if locked else "Lock")
        lock.setObjectName("textButton")
        lock.setToolTip("A locked card cannot be unpinned until it is unlocked.")
        lock.clicked.connect(lambda _c=False, item=pin_id, now=locked: self.pin_lock.emit(item, not now))
        unpin = QPushButton("Unpin")
        unpin.setObjectName("textButton")
        unpin.setEnabled(not locked)
        unpin.setToolTip("Locked. Unlock it first." if locked else "Takes the card off the board. Undo puts it back.")
        unpin.clicked.connect(lambda _c=False, item=pin_id: self.pin_unpin.emit(item))
        for button in (copy, open_button, lock, unpin):
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        return frame

    # ---------- the assistant ----------
    def _assistant_card(self) -> QWidget:
        """v3 Talk: the pond banner, then the last reply in the open (no box around it).

        The talk bar (Hold to talk, the typed line, send) is built here too but
        sits at the bottom of the Talk place, outside the scrolling part.
        """
        from PySide6.QtCore import QSize

        from babysitter.ui.icons import icon

        card = QWidget()
        card.setObjectName("talkBody")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.hero = HeroBanner(asset_path("hero.jpg"), asset_path("orb"), radius=16)
        self.hero.setToolTip("Your picture. It stays on this PC.")
        self.hero.set_reduced_motion(not _animations_wanted())
        picture = QPushButton("")
        picture.setObjectName("heroCorner")
        picture.setIcon(icon("image", "#e8ecf4", "#ffffff", 18))
        picture.setIconSize(QSize(18, 18))
        picture.setAccessibleName("Choose my picture")
        picture.setToolTip("Choose my picture. It's copied into your BabySitter folder, not uploaded.")
        picture.clicked.connect(self.choose_hero.emit)
        self.hero.set_corner_widget(picture)
        self.phase_word = self.hero.word
        self.phase_hint = self.hero.hint
        layout.addWidget(self.hero)

        body = QWidget()
        body.setObjectName("heroBody")
        layout.addWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(2, 22, 2, 8)
        layout.setSpacing(10)
        self.heard = QLabel("You: nothing yet.")
        self.heard.setWordWrap(True)
        self.heard.setObjectName("heardLine")
        layout.addWidget(self.heard)
        # v3: the spoken answer leads, in large type.
        self.spoken = QLabel("")
        self.spoken.setObjectName("spokenLarge")
        self.spoken.setWordWrap(True)
        self.spoken.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.spoken)
        # Lists, paths, and numbers open only when asked.
        self.reply_detail = QLabel("")
        self.reply_detail.setObjectName("detailMono")
        self.reply_detail.setWordWrap(True)
        self.reply_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.reply_detail.hide()
        layout.addWidget(self.reply_detail)

        actions = QHBoxLayout()
        actions.setSpacing(22)

        def action(text: str, icon_name: str, tip: str) -> QPushButton:
            button = QPushButton(text)
            button.setObjectName("textButton")
            button.setIcon(icon(icon_name, "#c6cddc", "#ffffff", 16))
            button.setIconSize(QSize(16, 16))
            button.setToolTip(tip)
            button.setCursor(Qt.PointingHandCursor)
            return button

        self.details_button = action("Show details", "chevron_down", "The lists, paths, and numbers behind the spoken answer.")
        self.details_button.clicked.connect(self._toggle_details)
        pin = action("Pin", "pin", "Pin this reply on the Board. It stays on this PC.")
        pin.clicked.connect(self.pin_reply.emit)
        copy = action("Copy", "copy", "Copies the reply that is on screen.")
        copy.clicked.connect(self.copy_reply.emit)
        fresh = action("Fresh start", "refresh", "Clears this conversation's context. Pins and memory stay.")
        fresh.clicked.connect(self.fresh_start.emit)
        # Only for a line that was heard but not sent yet (the push-to-talk review).
        self.send_button = action("Send what I heard", "arrow_right", "Sends the line to the local model. Nothing else goes with it.")
        self.send_button.clicked.connect(self.send_heard.emit)
        self.send_button.hide()
        for button in (self.details_button, pin, copy, fresh, self.send_button):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)

        # The talk bar: fixed at the bottom of Talk, outside the scrolling part.
        self.talk_bar = QFrame()
        self.talk_bar.setObjectName("talkBar")
        self.talk_bar.setProperty("noWrap", True)
        bar = QVBoxLayout(self.talk_bar)
        bar.setContentsMargins(24, 14, 24, 12)
        bar.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.hold = QPushButton("Turn the AI on")
        self.hold.setObjectName("holdButton")
        self.hold.setIcon(icon("mic", "#2a1606", "#2a1606", 20))
        self.hold.setIconSize(QSize(20, 20))
        self.hold.setToolTip("The microphone opens only while this is held. Space or Enter works too.")
        self.hold.setCursor(Qt.PointingHandCursor)
        self.hold.pressed.connect(self.hold_pressed.emit)
        self.hold.released.connect(self.hold_released.emit)
        row.addWidget(self.hold)
        self.typed = QLineEdit()
        self.typed.setObjectName("talkInput")
        self.typed.setAccessibleName("Type a question or command")
        self.typed.setPlaceholderText("Or type: remind me to stretch at 6")
        self.typed.setToolTip("A fallback for when you cannot talk (Ctrl+L focuses this box). The same rules apply.")
        self.typed.returnPressed.connect(lambda: self.command_submitted.emit(self.typed.text()))
        row.addWidget(self.typed, 1)
        run = QPushButton("")
        run.setObjectName("sendButton")
        run.setIcon(icon("arrow_right", "#c6cddc", "#ffffff", 20))
        run.setIconSize(QSize(20, 20))
        run.setAccessibleName("Run it")
        run.setToolTip("Runs the typed line. Actions still ask before they run.")
        run.setCursor(Qt.PointingHandCursor)
        run.clicked.connect(lambda: self.command_submitted.emit(self.typed.text()))
        row.addWidget(run)
        bar.addLayout(row)
        mic = QLabel("The microphone opens only while you hold the button.")
        mic.setObjectName("hint")
        bar.addWidget(mic)
        return card

    def set_compact_talk(self, compact: bool) -> None:
        """A narrow window: Hold to talk shows only its mic, so the typed line keeps its room."""
        self._compact_talk = bool(compact)
        words = self.hold.property("fullText") or self.hold.text() or "Turn the AI on"
        self.hold.setProperty("fullText", words)
        self.hold.setText("" if compact else str(words))

    def _toggle_details(self) -> None:
        from babysitter.ui.icons import icon

        showing = not self.reply_detail.isVisible()
        self.reply_detail.setVisible(showing and bool(self.reply_detail.text().strip()))
        self.details_button.setText("Hide details" if showing else "Show details")
        self.details_button.setIcon(icon("chevron_up" if showing else "chevron_down", "#c6cddc", "#ffffff", 16))

    # ---------- this PC ----------
    def _pc_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        title = QHBoxLayout()
        title.addWidget(self._section("THIS PC"))
        title.addStretch(1)
        refreshed = QLabel("Refreshes every 2 seconds")
        refreshed.setObjectName("hint")
        title.addWidget(refreshed)
        layout.addLayout(title)
        self.gpu_line = QLabel("Video memory")
        self.gpu_spark = Sparkline()
        self.gpu_gold = QLabel("—")
        self.gpu_gold.setObjectName("gold")
        layout.addLayout(self._meter(self.gpu_line, self.gpu_spark, self.gpu_gold))
        self.cpu_line = QLabel("CPU")
        self.cpu_spark = Sparkline()
        self.cpu_gold = QLabel("—")
        self.cpu_gold.setObjectName("gold")
        layout.addLayout(self._meter(self.cpu_line, self.cpu_spark, self.cpu_gold))
        self.ram_line = QLabel("RAM")
        self.ram_spark = Sparkline()
        self.ram_gold = QLabel("—")
        self.ram_gold.setObjectName("gold")
        layout.addLayout(self._meter(self.ram_line, self.ram_spark, self.ram_gold))
        vram_header = QHBoxLayout()
        vram_header.addWidget(self._section("VIDEO MEMORY"))
        vram_header.addStretch(1)
        self.vram_now = QLabel("—")
        self.vram_now.setObjectName("gold")
        vram_header.addWidget(self.vram_now)
        layout.addLayout(vram_header)
        self.vram_bars = BarChart()
        layout.addWidget(self.vram_bars)
        self.vram_caption = QLabel("Peak, now, and free show up after the first readings.")
        self.vram_caption.setObjectName("hint")
        self.vram_caption.setWordWrap(True)
        layout.addWidget(self.vram_caption)
        layout.addWidget(self._section("LOADED MODEL"))
        self.model_line = QLabel("Nothing is loaded.")
        self.model_line.setWordWrap(True)
        self.model_badge = QLabel("")
        self.model_badge.setObjectName("hint")
        layout.addWidget(self.model_line)
        layout.addWidget(self.model_badge)
        layout.addStretch(1)
        return card

    # ---------- what just happened ----------
    def _log_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        header = QHBoxLayout()
        header.addWidget(self._section("WHAT JUST HAPPENED"))
        header.addStretch(1)
        copy = QPushButton("Copy all")
        copy.setToolTip("Copies this log so you can paste an error.")
        copy.clicked.connect(self.copy_log.emit)
        header.addWidget(copy)
        layout.addLayout(header)
        self.recent = QPlainTextEdit()
        self.recent.setReadOnly(True)
        self.recent.setAccessibleName("Recent activity log")
        self.recent.setFixedHeight(140)
        self.recent.setToolTip("Select the text and copy it if you need to send an error.")
        layout.addWidget(self.recent)
        self.privacy = QLabel("Private to this computer. BabySitter does not send usage data.")
        self.privacy.setWordWrap(True)
        self.privacy.setObjectName("hint")
        self.privacy.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.privacy)
        layout.addStretch(1)
        return card

    # ---------- the same API the shell drives ----------
    def set_privacy(self, social_search_on: bool, google_on: bool = False) -> None:
        if social_search_on and google_on:
            self.privacy.setText(
                "Social search and Google mail and calendar are on. "
                "A search leaves only after you confirm. Mail and calendar are read with your token. "
                "BabySitter does not send usage data."
            )
            return
        if google_on:
            self.privacy.setText(
                "Google mail and calendar are on. BabySitter reads them with the token you saved. "
                "It does not send mail. BabySitter does not send usage data."
            )
            return
        if social_search_on:
            self.privacy.setText(
                "Social search is on. Only the words you confirm on the Tools tab can leave this PC. "
                "BabySitter does not send usage data. Turn social search off for confidential work."
            )
            return
        self.privacy.setText(
            "Private to this computer. BabySitter only talks to Ollama here. "
            "BabySitter does not send usage data."
        )

    def set_hero(self, path: str) -> None:
        if self.hero.set_image(path):
            return
        self.hero.hint.setText("That picture could not be opened.")

    def set_reply(self, heard: str, spoken: str, detail: str) -> None:
        self.heard.setText(f"You: {heard}")
        self.spoken.setText(spoken)
        self.reply_detail.setText(detail)
        # Each new reply starts with its details folded away.
        self.reply_detail.hide()
        self.details_button.setText("Show details")
        self.details_button.setVisible(bool((detail or "").strip()))

    def set_phase(self, phase: str, hint: str) -> None:
        self.hero.show_phase(phase, STATE_WORDS.get(phase, "On"), hint)

    def _banner(self, object_name: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName(object_name)
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(frame)
        label = QLabel("")
        label.setObjectName("bannerText")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout.addWidget(label)
        return frame

    def set_banner(self, frame: QFrame, text: str, visible: bool) -> None:
        frame.layout().itemAt(0).widget().setText(text)
        frame.setVisible(visible)

    def set_state(self, state: str, detail: str) -> None:
        self.power.set_state(state)
        self.power.setToolTip(detail)
        self.power_word.setText(STATE_WORDS.get(state, "Needs you"))
        self.power_word.setStyleSheet(f"color: {STATE_COLORS.get(state, STATE_COLORS['error'])};")
        self.power_hint.setText(CLICK_HINT.get(state, CLICK_HINT["error"]))
        self.try_again.setVisible(state == "error")
        # The one orange button says what a press will do.
        words = "Turn the AI on" if state == "off" else "Hold to talk"
        self.hold.setProperty("fullText", words)
        self.hold.setAccessibleName(words)
        self.hold.setText("" if getattr(self, "_compact_talk", False) else words)
        self.set_phase(state, detail)
        if state == "game":
            self.game.setText("Leave")
            self.game.setChecked(True)
            self.game.setEnabled(True)
            self.game_word.setText("On")
            self.game.setToolTip(
                "Leaves game mode and loads the model again, even if the game is still open."
            )
        elif state == "on":
            self.game.setText("Game mode")
            self.game.setChecked(False)
            self.game.setEnabled(True)
            self.game_word.setText("Off")
            self.game.setToolTip(
                "Unloads the model so a game can use the graphics card. "
                "This is the manual switch. A game can still switch by itself, or ask first, from Settings."
            )
        else:
            self.game.setText("Game mode")
            self.game.setChecked(False)
            self.game.setEnabled(False)
            self.game_word.setText("Off")
            self.game.setToolTip("Turn the AI on first. Game mode is for when a model is loaded.")

    def set_busy(self, busy: bool) -> None:
        for button in self.intel_buttons.values():
            button.setEnabled(not busy)

    def set_power_ready(self, ready: bool) -> None:
        self.power.setEnabled(ready)
        if not ready:
            self.power_hint.setText("Checking Ollama…")

    def set_intelligence(self, mode_id: str) -> None:
        mode = MODES.get(mode_id, MODES["medium"])
        for key, button in self.intel_buttons.items():
            button.setChecked(key == mode.id)
        self.intel_summary.setText(
            f"{mode.summary} Context {mode.num_ctx:,}. About {mode.vram_mib / 1024:.1f} GB of video memory."
        )

    def set_history(self, lines: list[str]) -> None:
        self.recent.setPlainText("\n".join(lines))

    def set_status(self, snap) -> None:
        if snap.gpu is None:
            self.gpu_line.setText(snap.gpu_error or "No video memory reading.")
            self.gpu_gold.setText("—")
        else:
            percent = 0
            if snap.gpu.total_mib:
                percent = round(100 * snap.gpu.used_mib / snap.gpu.total_mib)
            self._vram_samples.append(float(snap.gpu.used_mib))
            del self._vram_samples[:-60]
            self.gpu_spark.push(float(snap.gpu.used_mib))
            self.vram_bars.set_values(self._vram_samples)
            self.gpu_line.setText(f"Video memory\n{format_mib(snap.gpu.used_mib)} / {format_mib(snap.gpu.total_mib)}")
            self.gpu_gold.setText(f"{percent}%")
            self.vram_now.setText(format_mib(snap.gpu.used_mib))
            free = max(0, snap.gpu.total_mib - snap.gpu.used_mib)
            peak = max(self._vram_samples) if self._vram_samples else snap.gpu.used_mib
            self.vram_caption.setText(
                f"Peak {format_mib(int(peak))}   Now {format_mib(snap.gpu.used_mib)}   Free {format_mib(free)}"
            )
        if snap.cpu_percent is not None:
            # (A list of every processor reading used to be kept here too, never
            # trimmed and never read: one number every 2 seconds, forever.)
            self.cpu_spark.push(float(snap.cpu_percent))
            self.cpu_line.setText("CPU")
            self.cpu_gold.setText(f"{snap.cpu_percent:.0f}%")
        if snap.ram_total_bytes:
            ram_percent = round(100 * snap.ram_used_bytes / snap.ram_total_bytes)
            self.ram_spark.push(float(ram_percent))
            self.ram_line.setText(
                f"RAM\n{format_bytes(snap.ram_used_bytes)} / {format_bytes(snap.ram_total_bytes)}"
            )
            self.ram_gold.setText(f"{ram_percent}%")
        if snap.models_error:
            self.model_line.setText(snap.models_error)
            self.model_badge.setText("")
        elif not snap.port_open:
            self.model_line.setText("Ollama is not running.")
            self.model_badge.setText("No model is loaded.")
        elif not snap.models:
            self.model_line.setText("Ollama is running.")
            self.model_badge.setText("No model is loaded.")
        else:
            lines = []
            badges = []
            for model in snap.models:
                lines.append(model.name)
                badges.append(model.gpu_label)
            self.model_line.setText("\n".join(lines))
            self.model_badge.setText(" · ".join(badges))
        return any(classify_ollama_process(name) == "tray" for name in snap.process_names)

    def _card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        return frame

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        return label

    def _meter(self, caption: QLabel, spark: Sparkline, gold: QLabel) -> QGridLayout:
        grid = QGridLayout()
        caption.setWordWrap(True)
        grid.addWidget(caption, 0, 0)
        grid.addWidget(gold, 0, 1, alignment=Qt.AlignRight)
        grid.addWidget(spark, 1, 0, 1, 2)
        return grid
