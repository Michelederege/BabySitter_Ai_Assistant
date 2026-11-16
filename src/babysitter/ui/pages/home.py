"""Home, v2: the controls strip, the pinboard and the assistant, then
this PC and what just happened.

The order is fixed: controls first, the assistant beside the pinboard,
readings and the feed last. In half screen everything stacks into one
column, assistant first.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
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
from babysitter.status import format_bytes, format_mib
from babysitter.ui.pinbutton import pin_button
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
        self._cpu_samples: list[float] = []
        self._ram_samples: list[float] = []
        self._expanded = True
        self._side_by_side = True
        self._controls_columns = 0
        self._arrange()
        self._place_controls(4)

    # ---------- layout ----------
    def set_detailed(self, expanded: bool) -> None:
        self._expanded = expanded
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
    def _pin_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        header = QHBoxLayout()
        header.addWidget(self._section("PINBOARD"))
        header.addStretch(1)
        self.pin_count = QLabel(f"0 of {MAX_PINS}")
        self.pin_count.setObjectName("hint")
        header.addWidget(self.pin_count)
        layout.addLayout(header)
        note = QLabel("A few notes and results. Not a chat.")
        note.setObjectName("hint")
        layout.addWidget(note)
        self.pin_title = QLineEdit()
        self.pin_title.setPlaceholderText("Title")
        self.pin_title.setToolTip("A short name for the card. It stays on this PC.")
        self.pin_body = QLineEdit()
        self.pin_body.setPlaceholderText("The note to pin")
        self.pin_body.setToolTip("The words on the card. Nothing here is sent.")
        submit = pin_button()
        submit.setText("Pin")
        submit.setFixedSize(72, 28)
        submit.setToolTip("Puts this note on the board. It does not ask the model.")
        submit.clicked.connect(self._submit_pin)
        self.pin_body.returnPressed.connect(self._submit_pin)
        layout.addWidget(self.pin_title)
        layout.addWidget(self.pin_body)
        layout.addWidget(submit)
        self.pin_host = QWidget()
        self.pin_list = QVBoxLayout(self.pin_host)
        self.pin_list.setContentsMargins(0, 0, 0, 0)
        self.pin_list.setSpacing(8)
        layout.addWidget(self.pin_host)
        layout.addStretch(1)
        self.pins = QLabel("Nothing is pinned yet. Type a note above, or pin a reply.")
        self.pins.setWordWrap(True)
        self.pins.setObjectName("hint")
        self.pins.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.pins)
        return card

    def _submit_pin(self) -> None:
        title = self.pin_title.text().strip()
        body = self.pin_body.text().strip()
        if not title and not body:
            return
        self.pin_note.emit(title or body[:80], body or title)
        self.pin_title.clear()
        self.pin_body.clear()

    def set_pins(self, pins: list[dict]) -> None:
        while self.pin_list.count():
            item = self.pin_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        shown = pins[-MAX_PINS:]
        self.pin_count.setText(f"{len(shown)} of {MAX_PINS}")
        if not shown:
            self.pins.setText("Nothing is pinned yet. Type a note above, or pin a reply.")
            self.pins.show()
            return
        if len(pins) >= MAX_PINS:
            self.pins.setText("The board is full. Unpin a card before pinning another.")
            self.pins.show()
        else:
            self.pins.hide()
        for pin in shown:
            self.pin_list.addWidget(self._pin_item(pin))

    def _pin_item(self, pin: dict) -> QFrame:
        frame = QFrame()
        frame.setObjectName("innerCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        title = str(pin.get("title") or "Pinned")
        body = str(pin.get("body") or "")
        pin_id = str(pin.get("id") or "")
        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setToolTip(body)
        layout.addWidget(title_label)
        if body and body != title:
            preview = QLabel(body if len(body) <= 160 else body[:157] + "…")
            preview.setObjectName("hint")
            preview.setWordWrap(True)
            layout.addWidget(preview)
        row = QHBoxLayout()
        open_button = QPushButton("Open")
        open_button.setToolTip("Shows the whole card so you can copy it.")
        open_button.clicked.connect(lambda _c=False, item=pin_id: self.pin_open.emit(item))
        unpin = QPushButton("Unpin")
        unpin.setToolTip("Takes the card off the board. Nothing else is deleted.")
        unpin.clicked.connect(lambda _c=False, item=pin_id: self.pin_unpin.emit(item))
        row.addStretch(1)
        row.addWidget(open_button)
        row.addWidget(unpin)
        layout.addLayout(row)
        return frame

    # ---------- the assistant ----------
    def _assistant_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(self._section("ASSISTANT"))
        header.addStretch(1)
        picture = QPushButton("Choose my picture")
        picture.setToolTip("Copies a picture into your BabySitter folder. It is not uploaded.")
        picture.clicked.connect(self.choose_hero.emit)
        header.addWidget(picture)
        layout.addLayout(header)

        self.hero = QLabel("Your picture shows here.")
        self.hero.setAlignment(Qt.AlignCenter)
        self.hero.setMinimumHeight(150)
        self.hero.setMaximumHeight(170)
        self.hero.setWordWrap(True)
        self.hero.setToolTip("Your picture. It stays on this PC.")
        layout.addWidget(self.hero)

        badge = QHBoxLayout()
        self.phase_word = QLabel("Off")
        self.phase_word.setObjectName("word")
        self.phase_hint = QLabel("The microphone stays closed until you turn keyword listening on.")
        self.phase_hint.setObjectName("hint")
        self.phase_hint.setWordWrap(True)
        badge.addWidget(self.phase_word)
        badge.addWidget(self.phase_hint, 1)
        layout.addLayout(badge)

        self.heard = QLabel("You: nothing yet.")
        self.heard.setWordWrap(True)
        self.heard.setObjectName("hint")
        layout.addWidget(self.heard)
        layout.addWidget(self._section("SAID"))
        self.spoken = QLabel("")
        self.spoken.setObjectName("spoken")
        self.spoken.setWordWrap(True)
        self.spoken.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.spoken)
        layout.addWidget(self._section("ON SCREEN"))
        self.reply_detail = QLabel("")
        self.reply_detail.setWordWrap(True)
        self.reply_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.reply_detail)

        actions = QHBoxLayout()
        copy = QPushButton("Copy reply")
        copy.setToolTip("Copies the reply that is on screen.")
        copy.clicked.connect(self.copy_reply.emit)
        pin = pin_button()
        pin.setToolTip("Pin this reply on the board. It stays on this PC.")
        pin.clicked.connect(self.pin_reply.emit)
        send = QPushButton("Send what I heard")
        send.setToolTip("Sends the line to the local model. Nothing else goes with it.")
        send.clicked.connect(self.send_heard.emit)
        self.hold = QPushButton("Hold to talk")
        self.hold.setObjectName("primary")
        self.hold.setToolTip("The microphone opens only while this is held. Space or Enter works too.")
        self.hold.pressed.connect(self.hold_pressed.emit)
        self.hold.released.connect(self.hold_released.emit)
        actions.addWidget(copy)
        actions.addWidget(pin)
        actions.addWidget(send)
        actions.addWidget(self.hold)
        layout.addLayout(actions)

        type_row = QHBoxLayout()
        self.typed = QLineEdit()
        self.typed.setPlaceholderText("Or type it: remind me at 6 to stretch")
        self.typed.setToolTip("A fallback for when you cannot talk. The same rules apply.")
        self.typed.returnPressed.connect(lambda: self.command_submitted.emit(self.typed.text()))
        run = QPushButton("Run it")
        run.setToolTip("Runs the typed line. Actions still ask before they run.")
        run.clicked.connect(lambda: self.command_submitted.emit(self.typed.text()))
        type_row.addWidget(self.typed, 1)
        type_row.addWidget(run)
        layout.addLayout(type_row)
        layout.addStretch(1)
        return card

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
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.hero.setText("That picture could not be opened.")
            return
        self.hero.setPixmap(
            pixmap.scaled(self.hero.width() or 420, 170, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.hero.setText("")

    def set_reply(self, heard: str, spoken: str, detail: str) -> None:
        self.heard.setText(f"You: {heard}")
        self.spoken.setText(spoken)
        self.reply_detail.setText(detail)

    def set_phase(self, phase: str, hint: str) -> None:
        self.phase_word.setText(STATE_WORDS.get(phase, "On"))
        color = STATE_COLORS.get(phase, STATE_COLORS["on"])
        self.phase_word.setStyleSheet(f"color: {color};")
        self.phase_hint.setText(hint)

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
            self._cpu_samples.append(float(snap.cpu_percent))
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
