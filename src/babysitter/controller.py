"""Connects the window to the power switch.

The window never talks to Ollama directly. It asks this object, which does
the slow work on a background thread so the window stays responsive.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
import traceback
from datetime import date, datetime

from PySide6.QtCore import QObject, QThread, Signal

from babysitter import journal
from babysitter.audio import AudioGate
from babysitter.gamebudget import GameBudget, fitting_level, room_mib
from babysitter.games import GameWatch, clean_process_name, first_matching_game, foreground_process_name
from babysitter.quiet import in_quiet_hours, quiet_sentence
from babysitter.hotkeys import HotkeyBook, HotkeyError, UnavailableRegistrar, canonical_hotkey
from babysitter.intelligence import get_mode
from babysitter.logsetup import get_logger
from babysitter.ollama import OllamaClient, classify_ollama_process
from babysitter.paths import data_dir, logs_dir
from babysitter.platform import (
    autostart_command,
    default_autostart_backend,
    apply_game_core_avoidance,
    lower_own_priority,
    source_launcher_path,
    sync_autostart,
)
from babysitter.power import ERROR, GAME, OFF, ON, STARTING, PowerResult, PowerService
from babysitter.settings import Settings, load_settings, save_settings
from babysitter.startupcheck import VersionReport, check_ollama
from babysitter.status import StatusCollector, StatusSnapshot


log = get_logger()


class PowerThread(QThread):
    finished_job = Signal(object)
    progress = Signal(str)

    def __init__(self, service: PowerService, cancel: threading.Event) -> None:
        super().__init__()
        self.service = service
        self.cancel = cancel
        self.jobs: queue.Queue = queue.Queue()

    def submit(self, job: tuple) -> None:
        self.jobs.put(job)

    def run(self) -> None:
        while True:
            job = self.jobs.get()
            if job[0] == "quit":
                return
            try:
                result = self._dispatch(job)
            except Exception as exc:  # noqa: BLE001 — show the text, never hide a crash
                log.error("Power job failed:\n%s", traceback.format_exc())
                result = PowerResult(ERROR, f"Something broke inside the power switch: {exc}", False)
            self.finished_job.emit(result)

    def _dispatch(self, job: tuple) -> PowerResult:
        kind = job[0]
        if kind == "on":
            _kind, model, num_ctx, game_name, restart = job
            return self.service.turn_on(
                model=model,
                num_ctx=num_ctx,
                cancel=self.cancel,
                game_name=game_name,
                progress=self.progress.emit,
                restart_ollama=restart,
            )
        if kind == "reload":
            _kind, model, num_ctx = job
            return self.service.reload_model(
                model=model,
                num_ctx=num_ctx,
                cancel=self.cancel,
                progress=self.progress.emit,
            )
        if kind == "game":
            return self.service.enter_game_mode(progress=self.progress.emit)
        if kind == "off":
            _kind, emergency, tray_choice = job
            return self.service.turn_off(
                emergency=emergency,
                tray_choice=tray_choice,
                progress=self.progress.emit,
            )
        return PowerResult(ERROR, f"Unknown power job {kind}.", False)


class StatusThread(QThread):
    snapshot = Signal(object)
    version = Signal(object)

    def __init__(self, collector: StatusCollector, ollama: OllamaClient) -> None:
        super().__init__()
        self.collector = collector
        self.ollama = ollama
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        from babysitter.platform import mark_current_thread_efficient

        mark_current_thread_efficient()
        try:
            report = check_ollama(self.ollama)
        except Exception as exc:  # noqa: BLE001
            log.error("Version check failed:\n%s", traceback.format_exc())
            report = VersionReport(False, None, "", False, f"Could not check Ollama ({exc}).", False)
        self.version.emit(report)
        while not self._stop.is_set():
            try:
                snap = self.collector.snapshot()
            except Exception as exc:  # noqa: BLE001
                log.error("Status check failed: %s", exc)
                snap = StatusSnapshot(
                    cpu_percent=0,
                    ram_used_bytes=0,
                    ram_total_bytes=0,
                    port_open=False,
                    models_error=str(exc),
                    gpu_error=str(exc),
                )
            self.snapshot.emit(snap)
            if self._stop.wait(2.0):
                return


class Controller(QObject):
    state_changed = Signal(str, str)
    status_changed = Signal(object)
    version_changed = Signal(object)
    busy_changed = Signal(bool)
    reload_offered = Signal(bool)
    tray_prompt = Signal(str)
    confirm_old_version = Signal(str)
    # Ollama is already running from its own tray. Ask before using it.
    ollama_offer = Signal()
    notice = Signal(str)
    game_offer = Signal(str)
    quit_ready = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.settings: Settings = load_settings()
        from babysitter.intelligence import set_context

        set_context(self.settings.context_tokens)
        self.ollama = OllamaClient()
        self.audio = AudioGate()
        self.hotkeys = HotkeyBook()
        self.probe = StatusCollector(self.ollama)
        self.power = PowerService(self.ollama, self.probe, self.audio, self.hotkeys)
        self.games = GameWatch()
        self.budget = GameBudget()
        # The level really loaded. A game can push it below the one you picked.
        self.loaded_level = ""
        # The window says when a reply is being written or spoken. Nothing
        # switches level or unloads in the middle of one.
        self.reply_busy = lambda: False
        # True while a natural voice is chosen: it shares the card, so the AI runs on Low.
        self.voice_wants_card = lambda: False
        self.cancel = threading.Event()
        self.version: VersionReport | None = None
        self.latest_status: StatusSnapshot | None = None
        self.history: list[str] = []
        self._busy = False
        self._pending_off: tuple[bool, str] | None = None
        self._quit_after_off = False
        self.force_quit = False
        self._emergency_latched = False
        self.accepted_old_version = False
        # "restart" or "use", once answered, until BabySitter closes.
        self.outside_ollama_choice = ""
        self._game_prompt_open = False
        self.journal_paused = False
        self._journal_last = 0.0
        self._priority_note = lower_own_priority()
        self._core_note = apply_game_core_avoidance(self.settings.keep_off_game_cores)
        self.worker = PowerThread(self.power, self.cancel)
        self.status_thread = StatusThread(self.probe, self.ollama)
        self.worker.finished_job.connect(self._on_job)
        self.worker.progress.connect(self._on_progress)
        self.status_thread.snapshot.connect(self._on_status)
        self.status_thread.version.connect(self._on_version)

    @property
    def state(self) -> str:
        return self.power.state

    def start(self) -> None:
        self._remember(self._priority_note)
        self._remember("BabySitter opened with the AI off. Nothing is listening.")
        for note in self.settings.notices:
            self._remember(note)
            self.notice.emit(note)
        if self.settings.notices:
            save_settings(self.settings)
        self._sync_autostart()
        try:
            from babysitter.sessions import seal_old_files

            sealed = seal_old_files()
            if sealed:
                log.info("Encrypted %s History and fact files left in plain text by an older version.", sealed)
        except Exception as exc:  # noqa: BLE001
            log.error("Could not encrypt older History files: %s", exc)
        try:
            journal.prune(date.today())
        except OSError as exc:
            log.error("Could not tidy the journal folder: %s", exc)
        self.state_changed.emit(OFF, "The AI is off. Nothing is listening.")
        self.worker.start()
        self.status_thread.start()

    def shutdown_threads(self) -> None:
        self.stop_all_ai()
        self.status_thread.stop()
        self.worker.submit(("quit",))
        self.status_thread.wait(2000)
        self.worker.wait(2000)

    def stop_all_ai(self) -> None:
        """The last step before BabySitter exits: no model, helper, or Ollama it started stays behind."""
        try:
            from babysitter.plugins.voice.engines import release as release_engines

            release_engines()
        except Exception as exc:  # noqa: BLE001
            log.error("Could not close the voice engines: %s", exc)
        try:
            if self.ollama.we_started_server:
                self.ollama.stop_server()
        except Exception as exc:  # noqa: BLE001
            log.error("Could not stop Ollama at exit: %s", exc)

    def turn_on(self, *, ignore_old_version: bool = False, ollama_choice: str = "") -> None:
        if in_quiet_hours(
            self.settings.quiet_hours,
            self.settings.quiet_start,
            self.settings.quiet_end,
        ):
            message = quiet_sentence(self.settings.quiet_start, self.settings.quiet_end)
            self._remember(message)
            self.state_changed.emit(self.state, message)
            return
        if (
            self.version
            and self.version.older
            and not ignore_old_version
            and not self.accepted_old_version
        ):
            self.confirm_old_version.emit(self.version.message)
            return
        if ignore_old_version:
            self.accepted_old_version = True
        if ollama_choice:
            self.outside_ollama_choice = ollama_choice
        if (
            not self._busy
            and not self.outside_ollama_choice
            and not self.ollama.we_started_server
            and self.ollama.port_open()
        ):
            self.ollama_offer.emit()
            return
        if self._busy:
            self._remember("Still working on the last power change.")
            self.state_changed.emit(self.power.state, "Still working on the last power change.")
            return
        level, game_name = self._level_for_start()
        mode = get_mode(level)
        self.loaded_level = level
        self.cancel.clear()
        self._emergency_latched = False
        self._set_busy(True)
        self.state_changed.emit(STARTING, f"Starting… loading {mode.model}.")
        restart = self.outside_ollama_choice == "restart" and not self.ollama.we_started_server
        self.worker.submit(("on", mode.model, mode.num_ctx, game_name, restart))

    def _level_for_start(self) -> tuple[str, str | None]:
        """The level to load, and a game name when game mode should start instead.

        A game already running gets the highest level that fits beside it.
        When none fits, game mode starts, unless you woke the model on purpose.
        """
        chosen = self.settings.intelligence
        if self.voice_wants_card() and chosen != "low":
            self._remember("A natural voice is chosen, so the AI loads on Low and both fit on the graphics card.")
            chosen = "low"
        snap = self.latest_status
        if not self.settings.auto_game_mode or snap is None:
            return chosen, None
        game = self._game_match(snap)
        if game is None:
            return chosen, None
        may_unload = self.games.auto_switch_target(game) is not None
        if snap.gpu is None:
            return chosen, (game if may_unload else None)
        room = room_mib(snap.gpu.total_mib, snap.gpu.used_mib, snap.gpu.ollama_mib)
        level = fitting_level(chosen, room)
        if level is None:
            if may_unload:
                self.budget.entered_game(chosen)
                return chosen, game
            return "low", None
        if level != chosen:
            self.budget.restore_to = chosen
            self._remember(
                f"{game} is running. About {room:,} MB of video memory is left, so "
                f"{get_mode(level).label} is loading instead of {get_mode(chosen).label}."
            )
        return level, None

    def reply_mode(self):
        """The level a question must ask for: the one that is loaded.

        A game or a natural voice can load Low while your saved level is
        Medium or High. Asking for the saved level's model then made Ollama
        load the bigger model beside the game, which is what game mode was
        there to stop. Before anything is loaded, the saved level is used.
        """
        return get_mode(self.loaded_level or self.settings.intelligence)

    def reload_model(self, level: str | None = None) -> None:
        """Load a level. Without one, the level you picked. Settings are not changed."""
        if self._busy:
            return
        if level is None:
            # You asked for your own level. A game's switch-down is over.
            self.budget.restore_to = ""
        level = level or self.settings.intelligence
        if self.voice_wants_card() and level != "low":
            level = "low"
        mode = get_mode(level)
        self.loaded_level = level
        self.cancel.clear()
        self._set_busy(True)
        self.worker.submit(("reload", mode.model, mode.num_ctx))

    def enter_game(self, auto: bool = False) -> None:
        """Game mode. `auto` means a game's memory use asked for it, not you."""
        if self._busy:
            return
        if self.state == OFF:
            self.notice.emit("Turn the AI on first. Game mode unloads a model that is already loaded.")
            return
        if self.state == GAME:
            return
        if auto:
            self.budget.entered_game(self.settings.intelligence)
        else:
            # Your own choice. It is not undone when a game closes.
            self.budget.forget()
        self.games.suppress(None)
        self._set_busy(True)
        self.worker.submit(("game",))

    def wake(self) -> None:
        """Leave game mode and load the model, even if the game is still open."""
        match = None
        if self.latest_status is not None:
            match = self._game_match(self.latest_status)
        self.budget.forget()
        self.games.suppress(match)
        self.turn_on()

    def _game_match(self, snap: StatusSnapshot) -> str | None:
        """A game from your list, or one noticed by its install folder."""
        match = first_matching_game(self.settings.game_processes, snap.process_names)
        if match is None and self.settings.detect_games:
            match = snap.detected_game
        return match

    def turn_off(self, *, emergency: bool = False, tray_choice: str = "ask") -> None:
        if emergency:
            self._emergency_latched = True
            self.cancel.set()
            try:
                self.ollama.abort()
            except OSError as exc:
                log.error("Emergency abort failed: %s", exc)
            tray_choice = "close"
        if self._busy:
            self._pending_off = (emergency or self._emergency_latched, tray_choice)
            self.cancel.set()
            # A model load cannot be paused. If BabySitter started Ollama,
            # stop that process so Cancel does not sit there for a minute.
            if emergency or self.ollama.we_started_server:
                try:
                    self.ollama.abort()
                except OSError as exc:
                    log.error("Could not stop Ollama while cancelling: %s", exc)
            self._remember("Stopping…")
            return
        self._start_off(emergency or self._emergency_latched, tray_choice)

    def request_quit(self) -> str:
        """Return 'quit', 'ask', or 'wait'.

        'ask' means the window should ask whether to stop Ollama first.
        'wait' means a shutdown is already running and the app will close after.
        """
        if self._busy:
            self._quit_after_off = True
            # Closing BabySitter leaves no AI behind, the tray's Ollama included.
            self.turn_off(emergency=False, tray_choice="close")
            return "wait"
        if self.state in {ON, GAME, STARTING, ERROR} or self.ollama.port_open() or self.ollama.we_started_server:
            return "ask"
        return "quit"

    def quit_after_stopping(self) -> None:
        self._quit_after_off = True
        self.turn_off(emergency=False, tray_choice="close")

    def set_intelligence(self, mode_id: str) -> None:
        if mode_id not in {"low", "medium", "high"}:
            return
        self.settings.intelligence = mode_id
        # A level picked by its button uses that level's own amount of memory.
        self.settings.context_tokens = 0
        from babysitter.intelligence import set_context

        set_context(0)
        save_settings(self.settings)
        # A level you pick by hand replaces any switch-down a game made.
        self.budget.restore_to = ""
        offer = self.state == ON
        self.reload_offered.emit(offer)
        if self.state == GAME:
            self._remember("Intelligence saved. It applies the next time the model loads.")

    def set_context(self, tokens: int) -> str:
        """The memory slider, once it is let go. Returns the level it belongs to."""
        from babysitter.intelligence import level_for_context, set_context

        tokens = set_context(tokens)
        level = level_for_context(tokens) if tokens else self.settings.intelligence
        self.settings.context_tokens = tokens
        self.settings.intelligence = level
        self.budget.restore_to = ""
        save_settings(self.settings)
        if self.state == ON and not self._busy:
            self.reload_model()
        elif self.state == GAME:
            self._remember("The memory setting is saved. It applies the next time the model loads.")
        return level

    def set_always_on_top(self, enabled: bool) -> None:
        self.settings.orb_always_on_top = enabled
        save_settings(self.settings)

    def set_autostart(self, enabled: bool) -> str:
        self.settings.start_with_windows = enabled
        save_settings(self.settings)
        return self._sync_autostart()

    def set_hotkeys(self, emergency: str, power_on: str, registrar) -> list[str]:
        emergency = canonical_hotkey(emergency)
        power_on = canonical_hotkey(power_on)
        if emergency.lower() == power_on.lower():
            raise HotkeyError("The emergency key and the turn-on key must be different.")
        notes = self.hotkeys.apply(emergency, power_on, registrar)
        self.settings.emergency_hotkey = emergency
        self.settings.power_on_hotkey = power_on
        save_settings(self.settings)
        return notes

    def set_auto_game(self, enabled: bool) -> None:
        self.settings.auto_game_mode = enabled
        save_settings(self.settings)

    def set_game_ask(self, enabled: bool) -> None:
        self.settings.game_mode_ask = bool(enabled)
        save_settings(self.settings)

    def set_detect_games(self, enabled: bool) -> None:
        self.settings.detect_games = bool(enabled)
        save_settings(self.settings)

    def set_journal_enabled(self, enabled: bool) -> None:
        self.settings.journal_enabled = bool(enabled)
        save_settings(self.settings)

    def set_journal_paused(self, paused: bool) -> str:
        """Pause writing until it is resumed or the app restarts."""
        self.journal_paused = bool(paused)
        if paused:
            return "The journal is paused. Nothing is being written down."
        return "The journal is back on."

    def set_core_avoidance(self, enabled: bool) -> str:
        self.settings.keep_off_game_cores = bool(enabled)
        save_settings(self.settings)
        note = apply_game_core_avoidance(self.settings.keep_off_game_cores)
        self._core_note = note
        if not enabled:
            return "Core avoidance is off."
        return note or "Core avoidance is on."

    def add_game(self, name: str) -> str:
        cleaned = clean_process_name(name)
        if cleaned.lower() not in {item.lower() for item in self.settings.game_processes}:
            self.settings.game_processes.append(cleaned)
            save_settings(self.settings)
        return cleaned

    def remove_game(self, name: str) -> None:
        self.settings.game_processes = [
            item for item in self.settings.game_processes if item.lower() != name.lower()
        ]
        save_settings(self.settings)

    def add_journal_excluded(self, name: str) -> str:
        cleaned = clean_process_name(name)
        if len(self.settings.journal_excluded) >= 50:
            raise ValueError("Fifty excluded programs is the limit. Remove one first.")
        if cleaned.lower() not in {item.lower() for item in self.settings.journal_excluded}:
            self.settings.journal_excluded.append(cleaned)
            save_settings(self.settings)
        return cleaned

    def remove_journal_excluded(self, name: str) -> None:
        self.settings.journal_excluded = [
            item for item in self.settings.journal_excluded if item.lower() != name.lower()
        ]
        save_settings(self.settings)

    def remember_orb(self, x: int, y: int) -> None:
        self.settings.orb_x = int(x)
        self.settings.orb_y = int(y)
        save_settings(self.settings)

    def data_folder(self) -> str:
        return str(data_dir())

    def log_folder(self) -> str:
        return str(logs_dir())

    def _start_off(self, emergency: bool, tray_choice: str) -> None:
        self._set_busy(True)
        self.state_changed.emit(STARTING, "Turning off…")
        self.worker.submit(("off", emergency, tray_choice))

    def _on_progress(self, text: str) -> None:
        self._remember(text)
        self.state_changed.emit(self.power.state if self.power.state != OFF else STARTING, text)

    def _on_job(self, result: PowerResult) -> None:
        self._busy = False
        pending = self._pending_off
        self._pending_off = None
        if pending and result.state != OFF:
            emergency, choice = pending
            self._start_off(emergency, choice)
            return
        if result.message == "Stopped while starting." and not result.ok:
            self._start_off(self._emergency_latched, "close" if self._emergency_latched else "ask")
            return
        self._set_busy(False)
        self._apply(result)

    def _apply(self, result: PowerResult) -> None:
        self._remember(result.message)
        log.info("Power -> %s: %s", result.state, result.message)
        self.state_changed.emit(result.state, result.message)
        if result.needs_tray_close:
            self.tray_prompt.emit(result.message)
            return
        if result.state == ON:
            self.reload_offered.emit(False)
        if self._quit_after_off:
            # An update closes this copy no matter what, or the old version
            # stays open beside the new one. Ollama was stopped either way.
            if (result.state == OFF and result.ok) or self.force_quit:
                self.quit_ready.emit()
            else:
                self._quit_after_off = False
                self.notice.emit(
                    "I didn't close the app, because the AI may still be running. "
                    + result.message
                )

    def _on_status(self, snap: StatusSnapshot) -> None:
        self.latest_status = snap
        self.status_changed.emit(snap)
        self._journal_tick()
        if self._busy or not self.settings.auto_game_mode or self.state not in {ON, GAME}:
            return
        if self.reply_busy():
            # Never switch or unload while an answer is written or spoken.
            return
        game = self._game_match(snap)
        may_unload = game is not None and self.games.auto_switch_target(game) is not None
        if game is None:
            self.games.auto_switch_target(None)
        gpu = None
        if snap.gpu is not None:
            gpu = (snap.gpu.total_mib, snap.gpu.used_mib, snap.gpu.ollama_mib)
        ram_free = None
        if snap.ram_total_bytes:
            ram_free = max(0, int(snap.ram_total_bytes) - int(snap.ram_used_bytes))
        action = self.budget.decide(
            game=game,
            state=self.state,
            chosen=self.settings.intelligence,
            loaded=self.loaded_level or self.settings.intelligence,
            gpu=gpu,
            ram_free=ram_free,
            may_unload=may_unload,
        )
        self._carry_out(action, game)

    def _carry_out(self, action, game: str | None) -> None:
        if action.kind == "lower":
            label = get_mode(action.level).label
            self._remember(f"{action.reason} Switching to {label} until the game closes.")
            self.reload_model(action.level)
        elif action.kind == "restore":
            label = get_mode(action.level).label
            self._remember(f"{action.reason} Going back to {label}.")
            self.reload_model(action.level)
        elif action.kind == "leave_game":
            self._remember(f"{action.reason} Leaving game mode and loading the model again.")
            self.turn_on()
        elif action.kind == "game" and game:
            if self.settings.game_mode_ask:
                if self._game_prompt_open:
                    return
                self._game_prompt_open = True
                self.game_offer.emit(game)
                return
            self._remember(f"{action.reason} Switching to game mode.")
            self.enter_game(auto=True)

    def _journal_tick(self) -> None:
        """About twice a minute, write down the front program's name.

        Only while the AI is on or in game mode, only the file name, and
        only into a plain file in the personal folder.
        """
        if not self.settings.journal_enabled or self.journal_paused:
            return
        if self.state not in {ON, GAME}:
            return
        now = time.monotonic()
        if self._journal_last and now - self._journal_last < journal.SAMPLE_SECONDS:
            return
        self._journal_last = now
        try:
            app = foreground_process_name()
        except OSError:
            return
        if not app:
            return
        moment = datetime.now()
        try:
            record = journal.load_day(moment.date())
            if journal.record_sample(
                record, app, moment, excluded=self.settings.journal_excluded
            ):
                journal.save_day(record)
        except Exception as exc:  # noqa: BLE001 — the journal must never break the status loop
            log.error("Could not write the journal: %s", exc)

    def _on_version(self, report: VersionReport) -> None:
        self.version = report
        self._remember(report.message)
        self.version_changed.emit(report)

    def tray_is_running(self) -> bool:
        if self.latest_status is None:
            return bool(self.version and self.version.tray_running)
        return any(
            classify_ollama_process(name) == "tray" for name in self.latest_status.process_names
        )

    def close_tray_now(self) -> str:
        try:
            closed = self.ollama.close_tray()
        except OSError as exc:
            return f"Could not close the Ollama tray app ({exc})."
        if not closed:
            return "The Ollama tray app was not running."
        self._remember("Closed the Ollama tray app.")
        return "Closed the Ollama tray app."

    def _sync_autostart(self) -> str:
        if sys.platform != "win32":
            if self.settings.start_with_windows:
                return "Start with Windows only works on Windows. The switch has been left as you set it."
            return ""
        try:
            import sys as _sys

            frozen = bool(getattr(_sys, "frozen", False))
            command = autostart_command(
                frozen=frozen,
                executable=_sys.executable,
                source_launcher=str(source_launcher_path()) if not frozen else None,
            )
            sync_autostart(
                self.settings.start_with_windows,
                command,
                default_autostart_backend(),
            )
        except (OSError, ValueError) as exc:
            self.settings.start_with_windows = False
            save_settings(self.settings)
            message = f"Could not change Start with Windows ({exc}). It is off."
            self._remember(message)
            return message
        if self.settings.start_with_windows:
            return "BabySitter will start when you sign in to Windows. The AI will still start off."
        return "BabySitter will not start with Windows."

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)

    def _remember(self, text: str) -> None:
        if not text:
            return
        self.history.append(text)
        del self.history[:-12]
        log.info("%s", text)


def windows_registrar_or_dummy():
    if sys.platform != "win32":
        return UnavailableRegistrar()
    from babysitter.winhotkey import WinHotkeyRegistrar

    return WinHotkeyRegistrar()
