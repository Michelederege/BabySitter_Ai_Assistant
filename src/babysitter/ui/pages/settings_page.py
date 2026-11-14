"""Settings that exist in Phase 1. Later phases add to this same tab."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SettingsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        title = QLabel("Settings")
        title.setObjectName("title")
        intro = QLabel(
            "These are saved in your personal folder, not in the program folder, "
            "so an update will not wipe them. Start with Windows is off unless you turn it on."
        )
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        root.addWidget(title)
        root.addWidget(intro)

        self.autostart = QCheckBox("Start BabySitter when I sign in to Windows")
        self.autostart.setToolTip(
            "Off by default. The AI still starts off, so signing in does not load a model "
            "or open the microphone."
        )
        if sys.platform != "win32":
            self.autostart.setEnabled(False)
            self.autostart.setToolTip("This switch only works on Windows.")
        root.addWidget(self.autostart)

        self.on_top = QCheckBox("Keep the orb above other windows")
        self.on_top.setToolTip("The little floating light stays visible while you work. You can drag it.")
        root.addWidget(self.on_top)

        root.addWidget(self._label("Emergency stop key"))
        key_row = QHBoxLayout()
        self.emergency = QLineEdit()
        self.emergency.setReadOnly(True)
        self.emergency.setToolTip("Works even when the window is hidden. Default is Ctrl+Alt+F12.")
        self.emergency_change = QPushButton("Change")
        self.emergency_change.setToolTip("Press a new key combination. It is saved immediately.")
        key_row.addWidget(self.emergency)
        key_row.addWidget(self.emergency_change)
        root.addLayout(key_row)

        root.addWidget(self._label("Turn-on key"))
        on_row = QHBoxLayout()
        self.power_on = QLineEdit()
        self.power_on.setReadOnly(True)
        self.power_on.setToolTip(
            "Brings the AI back on. Default is Ctrl+Alt+F11. "
            "This key keeps working when other assistant keys are disabled."
        )
        self.power_change = QPushButton("Change")
        self.power_change.setToolTip("Press a new key combination. It is saved immediately.")
        on_row.addWidget(self.power_on)
        on_row.addWidget(self.power_change)
        root.addLayout(on_row)
        self.hotkey_note = QLabel("")
        self.hotkey_note.setWordWrap(True)
        self.hotkey_note.setObjectName("hint")
        root.addWidget(self.hotkey_note)

        self.auto_game = QCheckBox("Switch to game mode when a program below is running")
        self.auto_game.setToolTip(
            "Looks only at the program name. It does not read the game's memory "
            "and does not draw anything inside the game. Off by default."
        )
        root.addWidget(self.auto_game)
        self.off_game_cores = QCheckBox("Keep BabySitter off the game's processor cores")
        self.off_game_cores.setToolTip(
            "Off by default. On a Ryzen 9 7900X this uses logical processors 12 to 23. "
            "Leave it off until you have compared game frame times with it on and off."
        )
        root.addWidget(self.off_game_cores)

        self.quit_off = QCheckBox("Turn the AI off when quitting")
        self.quit_off.setToolTip(
            "On by default. Quit still asks first and tells you Ollama will be stopped."
        )
        root.addWidget(self.quit_off)

        root.addWidget(self._label("Listening extras"))
        hint = QLabel(
            "These stay off until you turn them on. Silero is used only when its file is already "
            "in your BabySitter folder. Otherwise a quiet-versus-loud check on the processor is used. "
            "None of this uses the graphics card."
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        root.addWidget(hint)
        self.vad_enabled = QCheckBox("Use Silero, or the processor check, to notice speech")
        self.vad_enabled.setToolTip("Off by default. Put silero_vad.onnx in models/silero to use Silero.")
        self.smart_turn = QCheckBox("Smart Turn: end the question sooner after a longer sentence")
        self.smart_turn.setToolTip("Off by default. A short question still waits a little longer.")
        self.echo_cancel = QCheckBox("Subtract BabySitter's own voice from the microphone")
        self.echo_cancel.setToolTip("Off by default. This is a simple subtract, not a studio canceller.")
        self.talk_over = QCheckBox("Let me talk over a reply")
        self.talk_over.setToolTip("Off by default. It only works while echo cancellation is also on.")
        for box in (self.vad_enabled, self.smart_turn, self.echo_cancel, self.talk_over):
            root.addWidget(box)
        self.games = QListWidget()
        self.games.setToolTip("Program names that count as games, such as bg3.exe.")
        root.addWidget(self.games)
        game_row = QHBoxLayout()
        self.add_game = QPushButton("Add from running programs")
        self.add_game.setToolTip("Shows programs open right now so you can pick a game.")
        self.type_game = QLineEdit()
        self.type_game.setPlaceholderText("or type a name, like game.exe")
        self.type_game.setToolTip("The file name only. A folder path is trimmed down to the file name.")
        self.add_typed = QPushButton("Add name")
        self.add_typed.setToolTip("Adds the name in the box.")
        self.remove_game = QPushButton("Remove")
        self.remove_game.setToolTip("Removes the selected name. The game itself is not changed.")
        game_row.addWidget(self.add_game)
        game_row.addWidget(self.type_game)
        game_row.addWidget(self.add_typed)
        game_row.addWidget(self.remove_game)
        root.addLayout(game_row)

        root.addWidget(self._label("Your files"))
        self.folder = QLabel("")
        self.folder.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.folder.setWordWrap(True)
        root.addWidget(self.folder)
        folder_row = QHBoxLayout()
        self.open_data = QPushButton("Open the data folder")
        self.open_data.setToolTip("Opens the folder where settings and logs are stored.")
        self.open_log = QPushButton("Open the log folder")
        self.open_log.setToolTip("Opens logs. They do not contain conversations.")
        folder_row.addWidget(self.open_data)
        folder_row.addWidget(self.open_log)
        root.addLayout(folder_row)
        root.addStretch(1)

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        return label

    def fill(self, settings, data_folder: str) -> None:
        self.autostart.setChecked(settings.start_with_windows)
        self.on_top.setChecked(settings.orb_always_on_top)
        self.emergency.setText(settings.emergency_hotkey)
        self.power_on.setText(settings.power_on_hotkey)
        self.auto_game.setChecked(settings.auto_game_mode)
        self.off_game_cores.setChecked(settings.keep_off_game_cores)
        self.quit_off.setChecked(settings.quit_turns_ai_off)
        self.vad_enabled.setChecked(settings.vad_enabled)
        self.smart_turn.setChecked(settings.smart_turn)
        self.echo_cancel.setChecked(settings.echo_cancel)
        self.talk_over.setChecked(settings.talk_over)
        self.games.clear()
        self.games.addItems(settings.game_processes)
        self.folder.setText(data_folder)

    def toggles(self):
        return (
            self.autostart,
            self.on_top,
            self.auto_game,
            self.off_game_cores,
            self.quit_off,
            self.vad_enabled,
            self.smart_turn,
            self.echo_cancel,
            self.talk_over,
        )
