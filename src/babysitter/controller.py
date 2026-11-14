"""Connects the window to the power switch.

The window never talks to Ollama directly. It asks this object, which does
the slow work on a background thread so the window stays responsive.
"""

from __future__ import annotations

import queue
import sys
import threading
import traceback

from PySide6.QtCore import QObject, QThread, Signal

from babysitter.audio import AudioGate
from babysitter.games import GameWatch, clean_process_name, first_matching_game
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
            _kind, model, num_ctx, game_name = job
            return self.service.turn_on(
                model=model,
                num_ctx=num_ctx,
                cancel=self.cancel,
                game_name=game_name,
                progress=self.progress.emit,
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
            if self._stop.wait(1):
                return


class Controller(QObject):
    state_changed = Signal(str, str)
    status_changed = Signal(object)
    version_changed = Signal(object)
    busy_changed = Signal(bool)
    reload_offered = Signal(bool)
    tray_prompt = Signal(str)
    confirm_old_version = Signal(str)
    notice = Signal(str)
    quit_ready = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.settings: Settings = load_settings()
        self.ollama = OllamaClient()
        self.audio = AudioGate()
        self.hotkeys = HotkeyBook()
        self.probe = StatusCollector(self.ollama)
        self.power = PowerService(self.ollama, self.probe, self.audio, self.hotkeys)
        self.games = GameWatch()
        self.cancel = threading.Event()
        self.version: VersionReport | None = None
        self.latest_status: StatusSnapshot | None = None
        self.history: list[str] = []
        self._busy = False
        self._pending_off: tuple[bool, str] | None = None
        self._quit_after_off = False
        self._emergency_latched = False
        self.accepted_old_version = False
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
        self.state_changed.emit(OFF, "The AI is off. Nothing is listening.")
        self.worker.start()
        self.status_thread.start()

    def shutdown_threads(self) -> None:
        self.status_thread.stop()
        self.worker.submit(("quit",))
        self.status_thread.wait(2000)
        self.worker.wait(2000)

    def turn_on(self, *, ignore_old_version: bool = False) -> None:
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
        if self._busy:
            self._remember("Still working on the last power change.")
            self.state_changed.emit(self.power.state, "Still working on the last power change.")
            return
        mode = get_mode(self.settings.intelligence)
        game_name = None
        if self.settings.auto_game_mode and self.latest_status is not None:
            match = first_matching_game(
                self.settings.game_processes, self.latest_status.process_names
            )
            game_name = self.games.auto_switch_target(match)
        self.cancel.clear()
        self._emergency_latched = False
        self._set_busy(True)
        self.state_changed.emit(STARTING, f"Starting… loading {mode.model}.")
        self.worker.submit(("on", mode.model, mode.num_ctx, game_name))

    def reload_model(self) -> None:
        if self._busy:
            return
        mode = get_mode(self.settings.intelligence)
        self.cancel.clear()
        self._set_busy(True)
        self.worker.submit(("reload", mode.model, mode.num_ctx))

    def enter_game(self) -> None:
        if self._busy:
            return
        if self.state == OFF:
            self.notice.emit("Turn the AI on first. Game mode unloads a model that is already loaded.")
            return
        if self.state == GAME:
            return
        self.games.suppress(None)
        self._set_busy(True)
        self.worker.submit(("game",))

    def wake(self) -> None:
        """Leave game mode and load the model, even if the game is still open."""
        match = None
        if self.latest_status is not None:
            match = first_matching_game(
                self.settings.game_processes, self.latest_status.process_names
            )
        self.games.suppress(match)
        self.turn_on()

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
            self.turn_off(emergency=False, tray_choice="ask")
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
        save_settings(self.settings)
        offer = self.state == ON
        self.reload_offered.emit(offer)
        if self.state == GAME:
            self._remember("Intelligence saved. It applies the next time the model loads.")

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
            if result.state == OFF and result.ok:
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
        if self._busy or not self.settings.auto_game_mode or self.state != ON:
            return
        match = first_matching_game(self.settings.game_processes, snap.process_names)
        target = self.games.auto_switch_target(match)
        if target:
            self._remember(f"{target} is running. Switching to game mode.")
            self.enter_game()

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
