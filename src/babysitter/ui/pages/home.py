"""Home, matching the slate control center.

The top row is power, intelligence, Normal/Game, and emergency stop.
Below that is this PC, the hero, the pinboard, and what just happened.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from babysitter.intelligence import MODES
from babysitter.ollama import classify_ollama_process
from babysitter.status import format_bytes, format_mib
from babysitter.ui.theme import STATE_COLORS, STATE_WORDS
from babysitter.ui.widgets import BarChart, PowerButton, Sparkline


CLICK_HINT = {
    "off": "Click to turn the AI on.",
    "starting": "Click to cancel.",
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
    copy_reply = Signal()
    copy_log = Signal()
    choose_hero = Signal()

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(18, 14, 18, 18)
        root.setSpacing(12)

        self.version_banner = self._banner("dangerBanner")
        self.tray_banner = self._banner("banner")
        self.tray_button = QPushButton("Close the Ollama tray app")
        self.tray_button.setToolTip(
            "Quits Ollama's own tray program so it cannot load a model by itself."
        )
        self.tray_banner.layout().addWidget(self.tray_button)
        self.version_banner.hide()
        self.tray_banner.hide()
        root.addWidget(self.version_banner)
        root.addWidget(self.tray_banner)

        controls = QHBoxLayout()
        controls.addWidget(self._power_card(), 2)
        controls.addWidget(self._intel_card(), 3)
        controls.addWidget(self._game_card(), 3)
        controls.addWidget(self._stop_card(), 3)
        root.addLayout(controls)

        self.detail_host = QWidget()
        detail = QVBoxLayout(self.detail_host)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(12)
        middle = QHBoxLayout()
        middle.addWidget(self._pc_card(), 4)
        middle.addWidget(self._hero_card(), 6)
        detail.addLayout(middle)
        bottom = QHBoxLayout()
        bottom.addWidget(self._pin_card(), 4)
        bottom.addWidget(self._vram_card(), 3)
        bottom.addWidget(self._log_card(), 4)
        detail.addLayout(bottom)
        root.addWidget(self.detail_host)
        root.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll)
        self._vram_samples: list[float] = []
        self._cpu_samples: list[float] = []
        self._ram_samples: list[float] = []

    def set_detailed(self, expanded: bool) -> None:
        self.detail_host.setVisible(expanded)

    def _power_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.addWidget(self._section("AI POWER"))
        row = QHBoxLayout()
        self.power = PowerButton()
        words = QVBoxLayout()
        self.power_word = QLabel("Off")
        self.power_word.setObjectName("word")
        self.power_hint = QLabel(CLICK_HINT["off"])
        self.power_hint.setObjectName("hint")
        self.power_hint.setWordWrap(True)
        words.addWidget(self.power_word)
        words.addWidget(self.power_hint)
        row.addWidget(self.power)
        row.addLayout(words)
        layout.addLayout(row)
        self.try_again = QPushButton("Try turning on")
        self.try_again.setToolTip("Tries to start Ollama and load the model again.")
        self.try_again.hide()
        layout.addWidget(self.try_again)
        return card

    def _intel_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.addWidget(self._section("INTELLIGENCE"))
        row = QHBoxLayout()
        self.intel_buttons: dict[str, QPushButton] = {}
        for mode_id in ("low", "medium", "high"):
            button = QPushButton(MODES[mode_id].label)
            button.setObjectName("choice")
            button.setCheckable(True)
            button.setToolTip(MODES[mode_id].summary)
            row.addWidget(button)
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
        return card

    def _game_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.addWidget(self._section("GAME MODE"))
        row = QHBoxLayout()
        self.game_word = QLabel("Off")
        self.game_word.setObjectName("word")
        self.game = QPushButton("Switch")
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
        self.game_note = QLabel("Click to unload the model and close the mic for gaming.")
        self.game_note.setObjectName("hint")
        self.game_note.setWordWrap(True)
        layout.addWidget(self.game_note)
        return card

    def _stop_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.addWidget(self._section("EMERGENCY STOP"))
        self.emergency = QPushButton("Stop everything now")
        self.emergency.setObjectName("danger")
        self.emergency.setToolTip("The same as Ctrl+Alt+F12. Turns the AI fully off from anywhere.")
        layout.addWidget(self.emergency)
        note = QLabel("Or press Ctrl+Alt+F12 anywhere, even when hidden.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        return card

    def _pc_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
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
        layout.addWidget(self._section("LOADED MODEL"))
        self.model_line = QLabel("Nothing is loaded.")
        self.model_line.setWordWrap(True)
        self.model_badge = QLabel("")
        self.model_badge.setObjectName("hint")
        layout.addWidget(self.model_line)
        layout.addWidget(self.model_badge)
        return card

    def _hero_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        self.hero = QLabel("Your picture shows here.")
        self.hero.setAlignment(Qt.AlignCenter)
        self.hero.setMinimumHeight(180)
        self.hero.setWordWrap(True)
        self.hero.setToolTip("Choose a picture. It stays on this PC. Off tints it grey.")
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
        self.heard = QLabel("I heard this: nothing yet.")
        self.heard.setWordWrap(True)
        self.spoken = QLabel("")
        self.spoken.setWordWrap(True)
        self.reply_detail = QLabel("")
        self.reply_detail.setWordWrap(True)
        self.reply_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.heard)
        layout.addWidget(self.spoken)
        layout.addWidget(self.reply_detail)
        actions = QHBoxLayout()
        copy = QPushButton("Copy")
        copy.setToolTip("Copies the reply that is on screen.")
        copy.clicked.connect(self.copy_reply.emit)
        pin = QPushButton("Pin this")
        pin.setObjectName("primary")
        pin.setToolTip("Pins this reply on the board. It stays on this PC.")
        pin.clicked.connect(self.pin_reply.emit)
        send = QPushButton("Send what I heard")
        send.setToolTip("Sends the line in the box to the local model. Nothing else goes with it.")
        send.clicked.connect(self.send_heard.emit)
        self.keyword_button = QPushButton("Listen for a keyword")
        self.keyword_button.setCheckable(True)
        self.keyword_button.setObjectName("primary")
        self.keyword_button.setToolTip(
            "While this is on and the AI is on, the microphone stays open for the keyword. "
            "The sound is checked on this PC. It is not saved and it is not sent."
        )
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("hey babysitter")
        self.keyword_edit.setToolTip("The words you say first. Two or three words work best.")
        self.hold = QPushButton("Hold to talk")
        self.hold.setToolTip("A backup. The microphone opens only while this is held.")
        self.hold.pressed.connect(self.hold_pressed.emit)
        self.hold.released.connect(self.hold_released.emit)
        actions.addWidget(self.keyword_button)
        actions.addWidget(copy)
        actions.addWidget(pin)
        actions.addWidget(send)
        actions.addWidget(self.hold)
        layout.addWidget(self.keyword_edit)
        layout.addLayout(actions)
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Or type it:"))
        self.typed = QLineEdit()
        self.typed.setPlaceholderText("remind me at 6 to stretch")
        self.typed.setToolTip("A fallback for when you cannot talk. The same rules apply.")
        self.typed.returnPressed.connect(lambda: self.command_submitted.emit(self.typed.text()))
        run = QPushButton("Run this command")
        run.setToolTip("Puts the line in “I heard this”. Actions still ask before they run.")
        run.clicked.connect(lambda: self.command_submitted.emit(self.typed.text()))
        type_row.addWidget(self.typed, 1)
        type_row.addWidget(run)
        layout.addLayout(type_row)
        picture = QPushButton("Choose my picture")
        picture.setToolTip("Copies a picture into your BabySitter folder. It is not uploaded.")
        picture.clicked.connect(self.choose_hero.emit)
        layout.addWidget(picture)
        return card

    def _pin_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        header = QHBoxLayout()
        header.addWidget(self._section("PINBOARD"))
        header.addStretch(1)
        note = QLabel("A few notes and results. Not a chat.")
        note.setObjectName("hint")
        header.addWidget(note)
        layout.addLayout(header)
        self.pins = QLabel("Nothing is pinned yet.")
        self.pins.setWordWrap(True)
        self.pins.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.pins)
        return card

    def _vram_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        header = QHBoxLayout()
        header.addWidget(self._section("VIDEO MEMORY"))
        header.addStretch(1)
        self.vram_now = QLabel("—")
        self.vram_now.setObjectName("gold")
        header.addWidget(self.vram_now)
        layout.addLayout(header)
        self.vram_bars = BarChart()
        layout.addWidget(self.vram_bars)
        self.vram_caption = QLabel("Peak, now, and free show up after the first readings.")
        self.vram_caption.setObjectName("hint")
        self.vram_caption.setWordWrap(True)
        layout.addWidget(self.vram_caption)
        return card

    def _log_card(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        header = QHBoxLayout()
        header.addWidget(self._section("WHAT JUST HAPPENED"))
        header.addStretch(1)
        copy = QPushButton("Copy")
        copy.setToolTip("Copies this log so you can paste an error.")
        copy.clicked.connect(self.copy_log.emit)
        header.addWidget(copy)
        layout.addLayout(header)
        self.recent = QPlainTextEdit()
        self.recent.setReadOnly(True)
        self.recent.setFixedHeight(120)
        self.recent.setToolTip("Select the text and copy it if you need to send an error.")
        layout.addWidget(self.recent)
        self.privacy = QLabel(
            "Private to this computer. BabySitter does not send usage data."
        )
        self.privacy.setWordWrap(True)
        self.privacy.setObjectName("hint")
        self.privacy.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.privacy)
        return card

    def set_privacy(self, social_search_on: bool) -> None:
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

    def set_pins_text(self, text: str) -> None:
        self.pins.setText(text)

    def set_hero(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.hero.setText("That picture could not be opened.")
            return
        self.hero.setPixmap(
            pixmap.scaled(self.hero.width() or 420, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.hero.setText("")

    def set_reply(self, heard: str, spoken: str, detail: str) -> None:
        self.heard.setText(f"I heard this: {heard}")
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
            self.game.setText("On")
            self.game.setChecked(True)
            self.game.setEnabled(True)
            self.game_word.setText("On")
            self.game.setToolTip("Loads the model again. The microphone stays closed until you hold to talk.")
        elif state == "on":
            self.game.setText("Off")
            self.game.setChecked(False)
            self.game.setEnabled(True)
            self.game_word.setText("Off")
        else:
            self.game.setText("Off")
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
        self.intel_summary.setText(f"{mode.summary} Context {mode.num_ctx:,}.")

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
