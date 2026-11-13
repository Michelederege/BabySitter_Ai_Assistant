"""The Home tab: the power switch and the live status cards."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from babysitter.intelligence import MODES
from babysitter.ollama import classify_ollama_process
from babysitter.status import format_bytes, format_mib
from babysitter.ui.widgets import Card, PowerButton


CLICK_HINT = {
    "off": "Click to turn the AI on",
    "starting": "Click to cancel",
    "on": "Click to turn the AI off",
    "game": "Click to turn the AI fully off",
    "error": "Click to make sure everything is off",
}


class HomePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        header = QLabel("Home")
        header.setObjectName("title")
        sub = QLabel(
            "The AI starts off. Nothing is listening until you turn it on. "
            "This phase is the power switch, game mode, and the status cards."
        )
        sub.setObjectName("hint")
        sub.setWordWrap(True)
        self.privacy = QLabel("")
        self.privacy.setObjectName("hint")
        self.privacy.setWordWrap(True)
        self.privacy.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(header)
        root.addWidget(sub)
        root.addWidget(self.privacy)

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

        row = QHBoxLayout()
        column = QVBoxLayout()
        self.power = PowerButton()
        self.power_hint = QLabel(CLICK_HINT["off"])
        self.power_hint.setObjectName("hint")
        self.power_hint.setAlignment(Qt.AlignHCenter)
        self.power_hint.setWordWrap(True)
        self.power_hint.setFixedWidth(200)
        column.addWidget(self.power, alignment=Qt.AlignHCenter)
        column.addWidget(self.power_hint)
        self.try_again = QPushButton("Try turning on")
        self.try_again.setToolTip("Tries to start Ollama and load the model again.")
        self.try_again.hide()
        column.addWidget(self.try_again)
        row.addLayout(column)

        side = QVBoxLayout()
        side.addWidget(QLabel("Intelligence"))
        intel_row = QHBoxLayout()
        self.intel_buttons: dict[str, QPushButton] = {}
        for mode_id in ("low", "medium", "high"):
            button = QPushButton(MODES[mode_id].label)
            button.setObjectName("choice")
            button.setCheckable(True)
            button.setToolTip(MODES[mode_id].summary)
            intel_row.addWidget(button)
            self.intel_buttons[mode_id] = button
        self.intel_buttons["medium"].setChecked(True)
        side.addLayout(intel_row)
        self.intel_summary = QLabel(MODES["medium"].summary)
        self.intel_summary.setWordWrap(True)
        self.intel_summary.setObjectName("hint")
        side.addWidget(self.intel_summary)
        self.reload = QPushButton("Reload the model with this setting")
        self.reload.setToolTip(
            "Unloads the model and loads it again so the new Low, Medium, or High setting applies."
        )
        self.reload.hide()
        side.addWidget(self.reload)

        game_row = QHBoxLayout()
        self.game = QPushButton("Game mode")
        self.game.setToolTip(
            "Unloads the model so a game can use the graphics card. "
            "Ollama stays running with nothing loaded. The microphone stays closed in this phase."
        )
        self.emergency = QPushButton("Emergency stop")
        self.emergency.setToolTip("The same as Ctrl+Alt+F12. Turns the AI fully off from anywhere.")
        game_row.addWidget(self.game)
        game_row.addWidget(self.emergency)
        side.addLayout(game_row)
        self.game_note = QLabel("Auto game mode is off.")
        self.game_note.setObjectName("hint")
        self.game_note.setWordWrap(True)
        side.addWidget(self.game_note)
        side.addStretch(1)
        row.addLayout(side, 1)
        root.addLayout(row)

        legend = QLabel("Grey off  ·  Yellow starting  ·  Green on  ·  Blue game mode  ·  Red needs you")
        legend.setObjectName("section")
        legend.setToolTip("These are the same colors as the floating orb.")
        root.addWidget(legend)

        grid = QGridLayout()
        self.gpu_card = Card(
            "Video memory",
            "From nvidia-smi. Shows how full the graphics card is, and whether Ollama is holding any of it.",
        )
        self.model_card = Card(
            "Loaded models",
            "Models Ollama currently has in memory. Only one should be loaded. 100% on the GPU means it is not spilling into system memory.",
        )
        self.pc_card = Card(
            "This computer",
            "CPU and memory use of the whole PC, from a local reading. Refreshes every 2 seconds.",
        )
        grid.addWidget(self.gpu_card, 0, 0)
        grid.addWidget(self.model_card, 0, 1)
        grid.addWidget(self.pc_card, 0, 2)
        root.addLayout(grid)

        recent_label = QLabel("What just happened")
        recent_label.setObjectName("section")
        recent_label.setToolTip("Plain-language notes from the power switch. You can select and copy them.")
        self.recent = QPlainTextEdit()
        self.recent.setReadOnly(True)
        self.recent.setFixedHeight(110)
        self.recent.setToolTip("Select the text and copy it if you need to send me an error.")
        root.addWidget(recent_label)
        root.addWidget(self.recent)

    def _banner(self, object_name: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName(object_name)
        layout = QVBoxLayout(frame)
        label = QLabel("")
        label.setObjectName("bannerText")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(label)
        return frame

    def set_banner(self, frame: QFrame, text: str, visible: bool) -> None:
        frame.layout().itemAt(0).widget().setText(text)
        frame.setVisible(visible)

    def set_privacy(self, social_search_on: bool) -> None:
        if social_search_on:
            self.privacy.setText(
                "Social search is on. Only the words you confirm on the Tools tab can leave this PC. "
                "Files, the screen, memory, and what you say to the assistant stay here. "
                "Turn social search off when the information is confidential."
            )
            self.privacy.setToolTip(
                "BabySitter still does not send usage data. The search box is the only thing that can leave."
            )
            return
        self.privacy.setText(
            "Private to this computer. BabySitter does not send usage data. "
            "What you tell the assistant stays on this PC, and social search is off."
        )
        self.privacy.setToolTip(
            "Ollama is contacted only at 127.0.0.1. No analytics, no account, no phone-home."
        )

    def set_state(self, state: str, detail: str) -> None:
        self.power.set_state(state)
        self.power.setToolTip(detail)
        self.power_hint.setText(CLICK_HINT.get(state, CLICK_HINT["error"]))
        self.try_again.setVisible(state == "error")
        if state == "game":
            self.game.setText("Wake the model")
            self.game.setEnabled(True)
            self.game.setToolTip("Loads the model again. If the game is still running, auto game mode will not immediately unload it.")
        elif state == "on":
            self.game.setText("Game mode")
            self.game.setEnabled(True)
        else:
            self.game.setText("Game mode")
            self.game.setEnabled(False)
            self.game.setToolTip("Turn the AI on first. Game mode is for when a model is loaded and you want the graphics card back.")

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
        self.intel_summary.setText(mode.summary + f" Uses {mode.model} with {mode.num_ctx:,} of context.")

    def set_history(self, lines: list[str]) -> None:
        self.recent.setPlainText("\n".join(lines))

    def set_status(self, snap) -> None:
        if snap.gpu is None:
            self.gpu_card.set_text(snap.gpu_error or "No video memory reading.")
        else:
            percent = 0
            if snap.gpu.total_mib:
                percent = round(100 * snap.gpu.used_mib / snap.gpu.total_mib)
            extra = ""
            if snap.gpu.ollama_mib:
                extra = f"\nOllama is holding about {format_mib(snap.gpu.ollama_mib)}."
            else:
                extra = "\nOllama is not holding video memory."
            note = f"\n{snap.gpu.index_note}" if snap.gpu.index_note else ""
            self.gpu_card.set_text(
                f"{format_mib(snap.gpu.used_mib)} used\nof {format_mib(snap.gpu.total_mib)}{extra}{note}",
                percent,
            )
        if snap.models_error:
            self.model_card.set_text(snap.models_error)
        elif not snap.port_open:
            self.model_card.set_text("Ollama is not running.\nNo model is loaded.")
        elif not snap.models:
            self.model_card.set_text("Ollama is running.\nNo model is loaded.")
        else:
            lines = []
            for model in snap.models:
                size = format_bytes(model.size_bytes) if model.size_bytes else "size unknown"
                lines.append(f"{model.name}\n{size} · {model.gpu_label}")
            self.model_card.set_text("\n\n".join(lines))
        if snap.ram_total_bytes:
            cpu = f"CPU  {snap.cpu_percent:.0f}%"
            ram = (
                f"Memory  {format_bytes(snap.ram_used_bytes)} of "
                f"{format_bytes(snap.ram_total_bytes)}"
            )
            self.pc_card.set_text(
                f"{cpu}\n{ram}",
                round(100 * snap.ram_used_bytes / snap.ram_total_bytes),
            )
        tray = any(classify_ollama_process(name) == "tray" for name in snap.process_names)
        return tray
