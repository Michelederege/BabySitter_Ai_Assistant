"""Settings that exist in Phase 1. Later phases add to this same tab."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from babysitter.ui.pinbutton import fill_pinned_list
from babysitter.version import __version__


class SettingsPage(QWidget):
    pin_line = Signal(str)
    # The chosen microphone's full name. Empty means Windows' default.
    microphone_chosen = Signal(str)
    hearing_chosen = Signal(str)

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

        root.addWidget(self._label("Updates"))
        update_row = QHBoxLayout()
        self.check_updates = QPushButton("Check for an update")
        self.check_updates.setAccessibleName("Check for an update")
        self.check_updates.setToolTip(
            "Checks Origin main when your BabySitter folder is on this PC, or GitHub Releases otherwise. "
            "Nothing is changed until you confirm."
        )
        self.install_update = QPushButton("Update BabySitter")
        self.install_update.setObjectName("primary")
        self.install_update.setAccessibleName("Update BabySitter")
        self.install_update.setToolTip(
            "Pulls the latest BabySitter update from Origin main (or GitHub Releases), "
            "rebuilds BabySitter.exe when needed, and restarts after you confirm."
        )
        update_row.addWidget(self.check_updates)
        update_row.addWidget(self.install_update)
        update_row.addStretch(1)
        root.addLayout(update_row)
        self.update_status = QLabel(
            f"Running BabySitter {__version__}. Click Check for an update or Update BabySitter anytime — "
            "no git push or PowerShell commands needed."
        )
        self.update_status.setWordWrap(True)
        self.update_status.setObjectName("hint")
        root.addWidget(self.update_status)

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
        self.emergency.setAccessibleName("Emergency stop key")
        self.emergency.setToolTip("Works even when the window is hidden. Default is Ctrl+Alt+F12.")
        self.emergency_change = QPushButton("Change")
        self.emergency_change.setAccessibleName("Change emergency stop key")
        self.emergency_change.setToolTip("Press a new key combination. It is saved immediately.")
        key_row.addWidget(self.emergency)
        key_row.addWidget(self.emergency_change)
        root.addLayout(key_row)

        root.addWidget(self._label("Turn-on key"))
        on_row = QHBoxLayout()
        self.power_on = QLineEdit()
        self.power_on.setReadOnly(True)
        self.power_on.setAccessibleName("Turn-on key")
        self.power_on.setToolTip(
            "Brings the AI back on. Default is Ctrl+Alt+F11. "
            "This key keeps working when other assistant keys are disabled."
        )
        self.power_change = QPushButton("Change")
        self.power_change.setAccessibleName("Change turn-on key")
        self.power_change.setToolTip("Press a new key combination. It is saved immediately.")
        on_row.addWidget(self.power_on)
        on_row.addWidget(self.power_change)
        root.addLayout(on_row)
        self.hotkey_note = QLabel("")
        self.hotkey_note.setWordWrap(True)
        self.hotkey_note.setObjectName("hint")
        root.addWidget(self.hotkey_note)

        self.auto_game = QCheckBox("Make room for a game by itself")
        self.auto_game.setToolTip(
            "While a game runs, BabySitter checks the graphics card every two seconds. If your level "
            "still fits beside the game, nothing changes. If only Low fits, it switches to Low. If "
            "nothing fits, it switches to game mode. Your level comes back when the game closes. "
            "It reads the program's name and folder and the card's memory, not the game itself."
        )
        root.addWidget(self.auto_game)
        self.game_mode_ask = QCheckBox("Ask me before unloading the model for a game")
        self.game_mode_ask.setToolTip(
            "Switching down to Low happens by itself. Unloading the model for game mode asks first. "
            "The Game mode button on Home still switches immediately."
        )
        root.addWidget(self.game_mode_ask)
        self.detect_games = QCheckBox("Count any program running from a game folder as a game")
        self.detect_games.setToolTip(
            "Steam's steamapps, Epic Games, GOG, the Xbox app, and Riot Games. A folder "
            "simply named Games does not count by itself. A game somewhere else still "
            "needs its name in the list below. On by default."
        )
        root.addWidget(self.detect_games)
        from babysitter.games import classified_examples

        lines = [f"{'Game' if counted else 'Not a game'} — {path}" for path, counted in classified_examples()]
        examples = QLabel("How folders are read:\n" + "\n".join(lines))
        examples.setObjectName("hint")
        examples.setWordWrap(True)
        examples.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(examples)
        self.hide_orb_for_games = QCheckBox("Hide the orb while a watched game is in front")
        self.hide_orb_for_games.setToolTip(
            "Off by default. This hides BabySitter's own light. It does not draw on the game."
        )
        root.addWidget(self.hide_orb_for_games)

        self.quiet_hours = QCheckBox("Quiet hours, when the AI refuses to turn on")
        self.quiet_hours.setToolTip("Off by default. Emergency stop still works. 22:00 to 07:00 wraps past midnight.")
        root.addWidget(self.quiet_hours)
        quiet_row = QHBoxLayout()
        self.quiet_start = QLineEdit()
        self.quiet_start.setPlaceholderText("22:00")
        self.quiet_start.setAccessibleName("Quiet hours start time")
        self.quiet_end = QLineEdit()
        self.quiet_end.setPlaceholderText("07:00")
        self.quiet_end.setAccessibleName("Quiet hours end time")
        self.quiet_save = QPushButton("Save quiet hours")
        quiet_row.addWidget(self.quiet_start)
        quiet_row.addWidget(self.quiet_end)
        quiet_row.addWidget(self.quiet_save)
        root.addLayout(quiet_row)

        self.side_button = QCheckBox("Use a mouse side button to talk while the AI is on")
        self.side_button.setToolTip(
            "Off by default. It does nothing while the AI is off or in Game mode. Windows only."
        )
        root.addWidget(self.side_button)

        self.searx_enabled = QCheckBox("Use SearXNG on this PC for web search")
        self.searx_enabled.setToolTip("Off by default. BabySitter only talks to 127.0.0.1.")
        root.addWidget(self.searx_enabled)
        searx_row = QHBoxLayout()
        self.searx_port = QLineEdit()
        self.searx_port.setPlaceholderText("8080")
        self.searx_port.setAccessibleName("SearXNG local port")
        self.searx_save = QPushButton("Save SearXNG port")
        searx_row.addWidget(self.searx_port)
        searx_row.addWidget(self.searx_save)
        root.addLayout(searx_row)

        self.off_game_cores = QCheckBox("Keep BabySitter off the game's processor cores")
        self.off_game_cores.setToolTip(
            "Off by default. On a Ryzen 9 7900X this uses logical processors 12 to 23. "
            "Leave it off until you have compared game frame times with it on and off."
        )
        root.addWidget(self.off_game_cores)

        self.quit_off = QCheckBox("The AI turns off when you quit or close the window")
        self.quit_off.setEnabled(False)
        self.quit_off.setToolTip(
            "This stays on. Quit and the X button unload the model, stop Ollama, "
            "and close the microphone. A model is not left running."
        )
        root.addWidget(self.quit_off)

        root.addWidget(self._label("Microphone"))
        mic_hint = QLabel(
            "Keyword listening and Talk both use this microphone. Windows' default is not always "
            "the one you talk into: a webcam or a dock can hold it and send no sound."
        )
        mic_hint.setWordWrap(True)
        mic_hint.setObjectName("hint")
        root.addWidget(mic_hint)
        mic_row = QHBoxLayout()
        self.microphone = QComboBox()
        self.microphone.setAccessibleName("Microphone")
        self.microphone.setToolTip("The microphone BabySitter opens. Nothing is recorded until you talk.")
        self.refresh_microphones = QPushButton("Refresh")
        self.refresh_microphones.setToolTip("Look again after plugging in or turning on a headset.")
        mic_row.addWidget(self.microphone, 1)
        mic_row.addWidget(self.refresh_microphones)
        root.addLayout(mic_row)
        self.microphone.activated.connect(
            lambda _index: self.microphone_chosen.emit(str(self.microphone.currentData() or ""))
        )

        root.addWidget(self._label("Speech recognition"))
        hearing_hint = QLabel(
            "One engine turns what you say into words, on the processor. Whisper is the default. "
            "Moonshine is much faster. Parakeet is more accurate. Each asks before it downloads."
        )
        hearing_hint.setWordWrap(True)
        hearing_hint.setObjectName("hint")
        root.addWidget(hearing_hint)
        from babysitter.plugins.voice.engines import HEARING_ENGINES

        self.hearing = QComboBox()
        self.hearing.setAccessibleName("Speech recognition engine")
        for engine_id, label in HEARING_ENGINES.items():
            self.hearing.addItem(label, engine_id)
        self.hearing.activated.connect(lambda _i: self.hearing_chosen.emit(str(self.hearing.currentData() or "whisper")))
        root.addWidget(self.hearing)

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
        self.games.setAccessibleName("Watched game programs")
        self.games.setToolTip("Program names that count as games, such as bg3.exe.")
        root.addWidget(self.games)
        game_row = QHBoxLayout()
        self.add_game = QPushButton("Add from running programs")
        self.add_game.setToolTip("Shows programs open right now so you can pick a game.")
        self.type_game = QLineEdit()
        self.type_game.setAccessibleName("Game program name")
        self.type_game.setPlaceholderText("or type a name, like game.exe")
        self.type_game.setToolTip("The file name only. A folder path is trimmed down to the file name.")
        self.add_typed = QPushButton("Add name")
        self.add_typed.setToolTip("Adds the name in the box.")
        self.remove_game = QPushButton("Remove")
        self.remove_game.setAccessibleName("Remove selected game")
        self.remove_game.setToolTip("Removes the selected name. The game itself is not changed.")
        game_row.addWidget(self.add_game)
        game_row.addWidget(self.type_game)
        game_row.addWidget(self.add_typed)
        game_row.addWidget(self.remove_game)
        root.addLayout(game_row)

        root.addWidget(self._label("Day journal"))
        journal_hint = QLabel(
            "The journal's switch lives on the Journal page. Only the front program's "
            "name and the minutes are written — no window titles, no keys, no "
            "screenshots. Days older than 90 days are deleted. Programs listed below "
            "are skipped and never written to the journal."
        )
        journal_hint.setWordWrap(True)
        journal_hint.setObjectName("hint")
        root.addWidget(journal_hint)
        self.journal_excluded = QListWidget()
        self.journal_excluded.setAccessibleName("Programs left out of the journal")
        self.journal_excluded.setToolTip("Program names skipped by the day journal, such as signal.exe.")
        root.addWidget(self.journal_excluded)
        excluded_row = QHBoxLayout()
        self.type_excluded = QLineEdit()
        self.type_excluded.setAccessibleName("Program to leave out of the journal")
        self.type_excluded.setPlaceholderText("program.exe, like signal.exe")
        self.type_excluded.setToolTip("The file name only. While this program is in front, the journal skips it.")
        self.add_excluded = QPushButton("Leave out")
        self.add_excluded.setToolTip("Stops writing this program's name into future journal minutes.")
        self.remove_excluded = QPushButton("Allow again")
        self.remove_excluded.setAccessibleName("Allow selected program in the journal again")
        self.remove_excluded.setToolTip("Takes the selected program off the skipped list.")
        excluded_row.addWidget(self.type_excluded, 1)
        excluded_row.addWidget(self.add_excluded)
        excluded_row.addWidget(self.remove_excluded)
        root.addLayout(excluded_row)
        self.wipe_journal = QPushButton("Wipe the journal")
        self.wipe_journal.setToolTip("Deletes every journal day file. There is no undo.")
        journal_row = QHBoxLayout()
        journal_row.addWidget(self.wipe_journal)
        journal_row.addStretch(1)
        root.addLayout(journal_row)

        root.addWidget(self._label("File search folders"))
        search_hint = QLabel(
            "Find my tax pdf looks in Documents, Downloads, and Desktop. Add a folder "
            "here, like a 3D-printing folder, to search it too. Nothing is indexed in "
            "the background and no file name leaves this PC."
        )
        search_hint.setWordWrap(True)
        search_hint.setObjectName("hint")
        root.addWidget(search_hint)
        self.search_folders = QListWidget()
        self.search_folders.setAccessibleName("Extra file search folders")
        self.search_folders.setToolTip("Extra folders the file search may look in.")
        root.addWidget(self.search_folders)
        search_row = QHBoxLayout()
        self.add_search_folder = QPushButton("Add a folder")
        self.add_search_folder.setToolTip("Pick a folder. Only its name is saved.")
        self.remove_search_folder = QPushButton("Remove")
        self.remove_search_folder.setAccessibleName("Remove selected search folder")
        self.remove_search_folder.setToolTip("Stops searching the selected folder. The folder itself is not changed.")
        search_row.addWidget(self.add_search_folder)
        search_row.addWidget(self.remove_search_folder)
        root.addLayout(search_row)

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
        self.game_mode_ask.setChecked(settings.game_mode_ask)
        self.detect_games.setChecked(settings.detect_games)
        self.off_game_cores.setChecked(settings.keep_off_game_cores)
        self.hide_orb_for_games.setChecked(settings.hide_orb_for_games)
        self.quiet_hours.setChecked(settings.quiet_hours)
        self.quiet_start.setText(settings.quiet_start)
        self.quiet_end.setText(settings.quiet_end)
        self.side_button.setChecked(settings.side_button)
        self.searx_enabled.setChecked(settings.searx_enabled)
        self.searx_port.setText(str(settings.searx_port))
        self.quit_off.setChecked(True)
        self.vad_enabled.setChecked(settings.vad_enabled)
        self.smart_turn.setChecked(settings.smart_turn)
        self.echo_cancel.setChecked(settings.echo_cancel)
        self.hearing.blockSignals(True)
        self.hearing.setCurrentIndex(max(0, self.hearing.findData(settings.hearing_engine)))
        self.hearing.blockSignals(False)
        self.talk_over.setChecked(settings.talk_over)
        games = [str(name) for name in settings.game_processes]
        excluded = [str(name) for name in settings.journal_excluded]
        folders = [str(name) for name in settings.search_folders]
        fill_pinned_list(self.games, [(name, name) for name in games], self.pin_line.emit)
        fill_pinned_list(self.journal_excluded, [(name, name) for name in excluded], self.pin_line.emit)
        fill_pinned_list(self.search_folders, [(name, name) for name in folders], self.pin_line.emit)
        if not games:
            self.games.addItem("No game names yet.")
        if not excluded:
            self.journal_excluded.addItem("No programs left out yet.")
        if not folders:
            self.search_folders.addItem("No extra folders yet.")
        self.folder.setText(data_folder)

    def set_microphones(self, names: list[str], saved: str, default: str) -> None:
        """Fill the list. A saved microphone that is unplugged stays listed."""
        self.microphone.blockSignals(True)
        self.microphone.clear()
        label = f"Windows default ({default})" if default else "Windows default"
        self.microphone.addItem(label, "")
        for name in names:
            self.microphone.addItem(name, name)
        if saved and saved not in names:
            self.microphone.addItem(f"{saved} (not found right now)", saved)
        index = self.microphone.findData(saved or "")
        self.microphone.setCurrentIndex(max(0, index))
        self.microphone.blockSignals(False)

    def toggles(self):
        return (
            self.autostart,
            self.on_top,
            self.auto_game,
            self.game_mode_ask,
            self.detect_games,
            self.off_game_cores,
            self.hide_orb_for_games,
            self.quiet_hours,
            self.side_button,
            self.searx_enabled,
            self.quit_off,
            self.vad_enabled,
            self.smart_turn,
            self.echo_cancel,
            self.talk_over,
        )
