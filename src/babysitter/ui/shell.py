"""Puts the window, the orb, and the tray on the same power switch."""

from __future__ import annotations

import base64
import ctypes
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QBuffer, QEvent, QIODevice, QObject, QRect, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMenu

from babysitter.commands import match_quick_command, timer_label
from babysitter.controller import Controller, windows_registrar_or_dummy
from babysitter.deskstore import add_item, hero_path, load_list
from babysitter.intelligence import get_mode
from babysitter.ollama import OllamaError, classify_ollama_process
from babysitter.hotkeys import EMERGENCY_ID, POWER_ON_ID, HotkeyError
from babysitter.paths import asset_path, data_dir
from babysitter.pictures import benchmark_warning, image_tokens, scaled_size
from babysitter.plugins.voice.keyword import (
    KeywordError,
    KeywordListener,
    clean_keyword,
    download_model as download_keyword_model,
    model_ready as keyword_model_ready,
    packages_installed as keyword_packages_installed,
)
from babysitter.plugins.voice.hearing import (
    HearingError,
    Recorder,
    download_model,
    install_packages,
    load_model,
    model_ready,
    packages_installed,
    release_model,
    transcribe,
)
from babysitter.plugins.voice.kokoro_voice import KokoroError, download as download_kokoro
from babysitter.plugins.voice.kokoro_voice import ready as kokoro_ready
from babysitter.plugins.voice.kokoro_voice import release as release_kokoro
from babysitter.plugins.voice.kokoro_voice import stop as stop_kokoro
from babysitter.plugins.voice.speech import (
    closed_lead,
    followup_phrase,
    interrupt_note,
    is_resume,
    lead_and_rest,
    more_answer,
    remainder_after,
    sapi_rate,
    speech_chunks,
    strip_thinking,
    voice_and_rest,
)
from babysitter.responsiveness import ResponsivenessLog, TurnClock
from babysitter.plugins.voice.windows_voice import WindowsVoiceError, speaker
from babysitter.plugins.tools.social import (
    PreparedSearch,
    SocialSearchError,
    perform,
    prepare,
)
from babysitter.secrets import SecretsError, default_vault
from babysitter.settings import save_settings
from babysitter.ui.dialogs import (
    HotkeyCapture,
    ProcessPicker,
    ask_three,
    ask_yes_no,
    show_copyable,
)
from babysitter.ui.main_window import MainWindow
from babysitter.ui.orb import Orb
from babysitter.ui.theme import STATE_WORDS
from babysitter.ui.tray import Tray


class _KeywordHub(QObject):
    phrase = Signal(str)
    status = Signal(str)
    failed = Signal(str)


class _KeywordDownloadJob(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.succeeded.emit(download_keyword_model())
        except KeywordError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class _WarmVoiceJob(QThread):
    def run(self) -> None:
        try:
            from babysitter.plugins.voice.kokoro_voice import warm

            warm()
        except Exception:
            return


def _png_base64(picture: QPixmap) -> str:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    picture.save(buffer, "PNG")
    return base64.b64encode(bytes(buffer.data())).decode("ascii")


class _BenchJob(QThread):
    finished_text = Signal(str)

    def __init__(self, ollama, model: str, num_ctx: int) -> None:
        super().__init__()
        self._ollama = ollama
        self._model = model
        self._num_ctx = num_ctx

    def run(self) -> None:
        from babysitter.pictures import format_benchmark

        samples: list[dict] = []
        try:
            for _ in range(3):
                started = time.perf_counter()
                stats: dict = {}
                for _piece in self._ollama.iter_reply(
                    self._model, "Reply with only the word ready.", self._num_ctx
                ):
                    stats = {}
                stats = dict(getattr(self._ollama, "last_turn_stats", {}) or {})
                stats.setdefault("wall_ms", int((time.perf_counter() - started) * 1000))
                samples.append(stats)
        except Exception as exc:
            self.finished_text.emit(f"The benchmark stopped. {exc}")
            return
        self.samples = samples
        self.finished_text.emit(format_benchmark(samples))


class _AskJob(QThread):
    first_token = Signal()
    lead_ready = Signal(str)
    succeeded = Signal(str)
    failed = Signal(str)
    measured = Signal(object)

    def __init__(self, ollama, model: str, prompt: str, num_ctx: int, history=None, images=None, keep_alive=-1) -> None:
        super().__init__()
        self._ollama = ollama
        self._model = model
        self._prompt = prompt
        self._num_ctx = num_ctx
        self._history = list(history or [])
        self._images = images
        self._keep_alive = keep_alive
        self.cancel = threading.Event()
        self.turn = 0

    def run(self) -> None:
        prompt = self._prompt
        self._prompt = ""
        parts: list[str] = []
        sent_lead = False
        sent_token = False
        try:
            for piece in self._ollama.iter_reply(
                self._model,
                prompt,
                self._num_ctx,
                self.cancel,
                self._history,
                self._images,
                self._keep_alive,
            ):
                self._images = None
                if self.cancel.is_set():
                    return
                parts.append(piece)
                if not sent_token:
                    self.first_token.emit()
                    sent_token = True
                if sent_lead:
                    continue
                lead = closed_lead(strip_thinking("".join(parts)))
                if lead:
                    self.lead_ready.emit(lead)
                    sent_lead = True
            if self.cancel.is_set():
                return
            reply = strip_thinking("".join(parts)).strip()
            stats = dict(getattr(self._ollama, "last_turn_stats", {}) or {})
            if stats:
                self.measured.emit(stats)
            if not reply:
                self.failed.emit("The model returned an empty reply.")
                return
            self.succeeded.emit(reply)
        except OllamaError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("The model did not answer.")
        finally:
            prompt = ""


class _KokoroDownloadJob(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.succeeded.emit(download_kokoro())
        except KokoroError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class _SpeakJob(QThread):
    started = Signal()
    phrase_done = Signal(str)
    failed = Signal(str)

    def __init__(self, text: str, prefs: dict, turn: int) -> None:
        super().__init__()
        self._text = text
        self._prefs = prefs
        self.turn = turn

    def run(self) -> None:
        text = self._text
        self._text = ""
        prefs = self._prefs
        try:
            pieces = speech_chunks(text)
            if prefs.get("engine") == "windows":
                announced = False
                for piece in pieces:
                    if not announced:
                        self.started.emit()
                        announced = True
                    speaker.speak(piece, voice=prefs.get("windows_voice", ""), rate=prefs.get("rate", 0))
                    self.phrase_done.emit(piece)
            else:
                from babysitter.plugins.voice.kokoro_voice import speak_sequence

                speak_sequence(
                    pieces,
                    prefs.get("name", ""),
                    prefs.get("speed", 105),
                    prefs.get("pitch", -1),
                    on_start=self.started.emit,
                    on_piece=self.phrase_done.emit,
                )
        except (WindowsVoiceError, KokoroError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc) or "The voice could not speak.")
        finally:
            text = ""


class _HearJob(QThread):
    heard = Signal(str)
    failed = Signal(str)

    def __init__(self, wav: bytes) -> None:
        super().__init__()
        self._wav = wav

    def run(self) -> None:
        wav = self._wav
        self._wav = b""
        try:
            self.heard.emit(transcribe(wav))
        except HearingError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Could not turn that recording into text. Nothing was sent.")
        finally:
            wav = b""


class _InstallHearingJob(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def run(self) -> None:
        try:
            if not packages_installed():
                install_packages()
            self.succeeded.emit(download_model())
        except HearingError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class _SearchJob(QThread):
    succeeded = Signal(str, str)
    failed = Signal(str)

    def __init__(self, prepared: PreparedSearch, api_key: str) -> None:
        super().__init__()
        self._prepared = prepared
        self._api_key = api_key

    def run(self) -> None:
        key = self._api_key
        self._api_key = ""
        try:
            outcome = perform(self._prepared, key)
            self.succeeded.emit(outcome.spoken, outcome.detail)
        except SocialSearchError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("The search stopped before it finished.")
        finally:
            key = ""


class _HideCharts(QObject):
    def __init__(self, collector) -> None:
        super().__init__()
        self._collector = collector

    def eventFilter(self, watched, event) -> bool:
        if event.type() in {QEvent.Type.Hide, QEvent.Type.Show}:
            self._collector.charts_paused = not watched.isVisible()
        return False


class Shell:
    def __init__(self, controller: Controller) -> None:
        self.controller = controller
        self.window = MainWindow()
        self.orb = Orb()
        self.icon = load_icon()
        self.window.setWindowIcon(self.icon)
        self.tray = Tray(self.icon)
        self.registrar = windows_registrar_or_dummy()
        self.vault = default_vault()
        self._search_job: _SearchJob | None = None
        self._power_ready = False
        self._turn_id = 0
        self._responsiveness = ResponsivenessLog()
        self._filler_n = 0
        self._finished_phrases: list[str] = []
        self._unheard = ""
        self._interrupt_note = ""
        self._history: list[dict] = []
        self._followup_left = 0
        self._logged_turn = False
        self._follow_timer = QTimer(self.window)
        self._follow_timer.setInterval(1000)
        self._follow_timer.timeout.connect(self._follow_tick)
        self._filler = QTimer(self.window)
        self._filler.setSingleShot(True)
        self._filler.timeout.connect(self._cue_waiting)
        self._connect()
        self._fill_settings()
        self._apply_hotkeys(
            controller.settings.emergency_hotkey,
            controller.settings.power_on_hotkey,
        )
        self._refresh_game_note()
        self.window.home.set_power_ready(False)
        self.window.home.set_intelligence(controller.settings.intelligence)
        self.orb.set_state("off", "The AI is off. Nothing is listening.")

    def show(self) -> None:
        self._place_orb()
        self.window.show()
        self.orb.set_always_on_top(self.controller.settings.orb_always_on_top)
        if sys.platform == "win32" and hasattr(self.registrar, "install_filter"):
            app = QApplication.instance()
            self.registrar.install_filter(app, self._on_hotkey_id)
            # Register again now that the filter is installed.
            self._apply_hotkeys(
                self.controller.settings.emergency_hotkey,
                self.controller.settings.power_on_hotkey,
            )
        self.controller.start()

    def show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
        self.window.stack.setCurrentWidget(self.window.home)
        home_button = self.window.nav_group.button(0)
        if home_button is not None:
            home_button.setChecked(True)

    def _connect(self) -> None:
        home = self.window.home
        settings = self.window.settings_page
        home.power.clicked.connect(self._on_power)
        home.try_again.clicked.connect(self._turn_on)
        home.game.clicked.connect(self._on_game)
        home.emergency.clicked.connect(lambda: self.controller.turn_off(emergency=True))
        home.reload.clicked.connect(self.controller.reload_model)
        home.tray_button.clicked.connect(self._close_tray)
        for mode_id, button in home.intel_buttons.items():
            button.clicked.connect(lambda _checked=False, mode=mode_id: self._set_intel(mode))
        self.orb.clicked.connect(self.show_window)
        self.orb.menu_requested.connect(self._popup_menu)
        self.orb.moved.connect(self.controller.remember_orb)
        self.tray.icon.activated.connect(self._tray_activated)
        self.tray.menu.aboutToShow.connect(lambda: self._fill_menu(self.tray.menu))
        self.controller.state_changed.connect(self._on_state)
        self.controller.status_changed.connect(self._on_status)
        self.controller.version_changed.connect(self._on_version)
        self.controller.busy_changed.connect(home.set_busy)
        self.controller.reload_offered.connect(home.reload.setVisible)
        self.controller.tray_prompt.connect(self._on_tray_prompt)
        self.controller.confirm_old_version.connect(self._on_old_version)
        self.controller.notice.connect(self._on_notice)
        self.controller.quit_ready.connect(self._finish_quit)
        settings.autostart.toggled.connect(self._set_autostart)
        settings.on_top.toggled.connect(self._set_on_top)
        settings.auto_game.toggled.connect(self._set_auto_game)
        settings.off_game_cores.toggled.connect(self._set_core_avoidance)
        self._hide_charts = _HideCharts(self.controller.probe)
        self.window.installEventFilter(self._hide_charts)
        settings.emergency_change.clicked.connect(self._change_emergency)
        settings.power_change.clicked.connect(self._change_power_key)
        settings.add_game.clicked.connect(self._add_running_game)
        settings.add_typed.clicked.connect(self._add_typed_game)
        settings.remove_game.clicked.connect(self._remove_game)
        settings.open_data.clicked.connect(lambda: open_folder(self.controller.data_folder()))
        settings.open_log.clicked.connect(lambda: open_folder(self.controller.log_folder()))
        tools = self.window.tools_page
        tools.enabled_changed.connect(self._set_social)
        tools.save_key.connect(self._save_social_key)
        tools.delete_key.connect(self._delete_social_key)
        tools.search_requested.connect(self._prepare_search)
        tools.set_enabled(self.controller.settings.social_search_enabled)
        self.window.home.set_privacy(self.controller.settings.social_search_enabled)
        saved = self.vault.has_key() if self.vault.available else False
        tools.set_key_saved(saved, self.vault.available)
        self.window.expand_button.clicked.connect(self._toggle_expand)
        self.window.set_expanded(self.controller.settings.window_expanded)
        self.window.pin_open.connect(self._show_pin)
        home.hold_pressed.connect(self._hold_down)
        home.hold_released.connect(self._hold_up)
        home.command_submitted.connect(self._on_command)
        home.send_heard.connect(self._send_heard)
        home.pin_reply.connect(self._pin_reply)
        home.copy_reply.connect(self._copy_reply)
        home.copy_log.connect(self._copy_log)
        home.choose_hero.connect(self._choose_hero)
        self.window.voice_page.notice.connect(self._on_page_notice)
        self.window.voice_page.followup[1].setValue(self.controller.settings.followup_seconds)
        self.window.schedule_page.notice.connect(self._on_page_notice)
        self.window.memory_page.notice.connect(self._on_page_notice)
        self.window.screen_page.notice.connect(self._on_page_notice)
        self.window.health_page.notice.connect(self._on_page_notice)
        self.window.models_page.notice.connect(self._on_page_notice)
        settings.quit_off.toggled.connect(self._set_quit_off)
        self._refresh_pins()
        if hero_path().is_file():
            self.window.home.set_hero(str(hero_path()))
        self._recorder = Recorder()
        self._listener = KeywordListener()
        self._keyword_hub = _KeywordHub()
        self._keyword_hub.phrase.connect(self._heard)
        self._keyword_hub.status.connect(self._keyword_status)
        self._keyword_hub.failed.connect(self._keyword_failed)
        home.keyword_button.toggled.connect(self._toggle_keyword)
        home.keyword_edit.editingFinished.connect(self._save_keyword)
        self._show_keyword()
        self._ptt_timer = QTimer(self.window)
        self._ptt_timer.timeout.connect(self._ptt_tick)
        self._ptt_timer.start(40)

    def _set_social(self, on: bool) -> None:
        self.controller.settings.social_search_enabled = bool(on)
        save_settings(self.controller.settings)
        self.window.home.set_privacy(bool(on))

    def _save_social_key(self, raw: str) -> None:
        page = self.window.tools_page
        try:
            self.vault.save(raw)
        except SecretsError as exc:
            page.set_key_saved(self.vault.has_key() if self.vault.available else False, self.vault.available)
            page.show_message(str(exc))
            return
        page.set_key_saved(True, self.vault.available)
        page.show_message("The key is saved. It is not shown again, and it is not stored in settings.json.")

    def _delete_social_key(self) -> None:
        page = self.window.tools_page
        if not ask_yes_no(
            self.window,
            "Delete the saved key?",
            "This removes the encrypted ScrapeCreators key from this PC. Searches will stop until you save a key again.",
            "Delete the key",
            "Keep it",
        ):
            return
        try:
            self.vault.delete()
        except SecretsError as exc:
            page.show_message(str(exc))
            return
        page.set_key_saved(False, self.vault.available)
        page.show_message("The saved key was deleted. Nothing was sent.")

    def _prepare_search(self, action_id: str, text: str) -> None:
        page = self.window.tools_page
        if self._search_job is not None and self._search_job.isRunning():
            page.show_message("A search is already running.")
            return
        if not self.controller.settings.social_search_enabled:
            page.show_message("Social search is off. Nothing was sent.")
            return
        try:
            prepared = prepare(action_id, text)
        except SocialSearchError as exc:
            page.show_message(str(exc))
            return
        if not ask_yes_no(
            self.window,
            "Send this search?",
            prepared.ask,
            "Send this search",
            "Don't send",
        ):
            page.show_message("Nothing was sent.")
            return
        try:
            key = self.vault.load() or ""
        except SecretsError as exc:
            page.show_message(str(exc))
            return
        if not key:
            page.show_message("Save an API key first. Nothing was sent.")
            return
        page.show_message("Searching public posts…", busy=True)
        job = _SearchJob(prepared, key)
        self._search_job = job
        job.succeeded.connect(self._search_ok)
        job.failed.connect(page.show_message)
        job.start()

    def _search_ok(self, spoken: str, detail: str) -> None:
        self.window.tools_page.show_message(spoken + "\n\n" + detail)

    def _on_power(self) -> None:
        if not self._power_ready and self.controller.state == "off" and not self.controller._busy:
            return
        if self.controller._busy or self.controller.state in {"on", "game", "starting", "error"}:
            self.controller.turn_off()
            return
        self._turn_on()

    def _turn_on(self) -> None:
        self.controller.turn_on()

    def _on_game(self) -> None:
        if self.controller.state == "game":
            self.controller.wake()
        else:
            self.controller.enter_game()

    def _on_state(self, state: str, message: str) -> None:
        self.window.home.set_state(state, message)
        self.window.home.set_history(self.controller.history)
        self.orb.set_state(state, message)
        self.window.set_chip(state, STATE_WORDS.get(state, "ERROR"))
        word = STATE_WORDS.get(state, "Needs you")
        self.tray.set_tooltip(f"BabySitter: {word}. {message}")
        self._sync_keyword()
        if state == "off":
            release_model()
            release_kokoro()
            self._return_to_game = False
            timer = getattr(self, "_game_return_timer", None)
            if timer is not None:
                timer.stop()
        if state == "on":
            self._warm_voice()
            self._warm_hearing()
            self._arm_game_return()
            queued = getattr(self, "_queued_after_load", "")
            if queued:
                self._queued_after_load = ""
                self._pending_line = queued
                self._send_heard()
        self.window.home.emergency.setToolTip(
            f"The same as {self.controller.settings.emergency_hotkey}. "
            "Turns the AI fully off, even if this window is hidden."
        )

    def _warm_hearing(self) -> None:
        if not packages_installed() or not model_ready():
            return
        if getattr(self, "_hearing_job", None) is not None and self._hearing_job.isRunning():
            return

        class _Job(QThread):
            def run(self_job) -> None:
                try:
                    load_model()
                except Exception:
                    return

        job = _Job()
        self._hearing_job = job
        job.start()

    def _warm_voice(self) -> None:
        if getattr(self, "_warm_job", None) is not None and self._warm_job.isRunning():
            return
        job = _WarmVoiceJob()
        self._warm_job = job
        job.start()

    def _on_status(self, snap) -> None:
        self.window.home.set_status(snap)
        self._refresh_game_note()
        tray = any(classify_ollama_process(name) == "tray" for name in snap.process_names)
        if tray:
            self.window.home.tray_button.show()
            self._show_tray_banner()
        elif self.controller.state == "off" and snap.port_open:
            self.window.home.set_banner(
                self.window.home.tray_banner,
                "Ollama is running even though BabySitter is off. "
                "Use Emergency stop if you want it fully stopped.",
                True,
            )
            self.window.home.tray_button.hide()
        else:
            self.window.home.tray_banner.hide()
            self.window.home.tray_button.show()

    def _on_version(self, report) -> None:
        self._power_ready = True
        self.window.home.set_power_ready(True)
        show = (not report.found) or report.older
        self.window.home.set_banner(self.window.home.version_banner, report.message, show)
        if report.tray_running:
            self._show_tray_banner()

    def _on_notice(self, text: str) -> None:
        self.show_window()
        show_copyable(self.window, "BabySitter", text)

    def _on_old_version(self, message: str) -> None:
        self.show_window()
        agreed = ask_yes_no(
            self.window,
            "Ollama needs an update",
            message + "\n\nTurn the AI on anyway?",
            "Turn on anyway",
            "Leave it off",
        )
        if agreed:
            self.controller.turn_on(ignore_old_version=True)

    def _on_tray_prompt(self, message: str) -> None:
        self.show_window()
        close_it = ask_yes_no(
            self.window,
            "Ollama's tray app is running",
            message,
            "Close the tray app",
            "Leave it running",
        )
        self.controller.turn_off(
            emergency=False,
            tray_choice="close" if close_it else "leave",
        )

    def _close_tray(self) -> None:
        message = self.controller.close_tray_now()
        self.window.home.set_history(self.controller.history)
        self.window.home.set_banner(self.window.home.tray_banner, message, "Could not" in message)

    def _show_tray_banner(self) -> None:
        self.window.home.set_banner(
            self.window.home.tray_banner,
            "Ollama's own tray app is running. It can load a model by itself and hold video memory "
            "even when BabySitter is off.",
            True,
        )

    def _set_intel(self, mode_id: str) -> None:
        self.controller.set_intelligence(mode_id)
        self.window.home.set_intelligence(mode_id)

    def _set_autostart(self, enabled: bool) -> None:
        message = self.controller.set_autostart(enabled)
        if message:
            self.controller._remember(message)
            self.window.home.set_history(self.controller.history)

    def _set_on_top(self, enabled: bool) -> None:
        self.controller.set_always_on_top(enabled)
        self.orb.set_always_on_top(enabled)

    def _set_auto_game(self, enabled: bool) -> None:
        self.controller.set_auto_game(enabled)
        self._refresh_game_note()

    def _set_core_avoidance(self, enabled: bool) -> None:
        note = self.controller.set_core_avoidance(enabled)
        if note:
            self.window.home.set_phase(self.controller.state, note)

    def _change_emergency(self) -> None:
        self._capture_key("emergency stop", emergency=True)

    def _change_power_key(self) -> None:
        self._capture_key("turning the AI on", emergency=False)

    def _capture_key(self, purpose: str, emergency: bool) -> None:
        dialog = HotkeyCapture(self.window, purpose)
        if dialog.exec() != QDialog.Accepted or not dialog.chosen:
            return
        if emergency:
            pair = (dialog.chosen, self.controller.settings.power_on_hotkey)
        else:
            pair = (self.controller.settings.emergency_hotkey, dialog.chosen)
        try:
            notes = self.controller.set_hotkeys(pair[0], pair[1], self.registrar)
        except HotkeyError as exc:
            show_copyable(self.window, "That key was not saved", str(exc))
            return
        self._fill_settings()
        self.window.settings_page.hotkey_note.setText(" ".join(notes) if notes else "Saved.")

    def _add_running_game(self) -> None:
        picker = ProcessPicker(self.window)
        if picker.exec() != QDialog.Accepted or not picker.chosen:
            return
        self._store_game(picker.chosen)

    def _add_typed_game(self) -> None:
        self._store_game(self.window.settings_page.type_game.text())

    def _store_game(self, name: str) -> None:
        try:
            self.controller.add_game(name)
        except ValueError as exc:
            show_copyable(self.window, "That name was not added", str(exc))
            return
        self.window.settings_page.type_game.clear()
        self._fill_settings()
        self._refresh_game_note()

    def _remove_game(self) -> None:
        item = self.window.settings_page.games.currentItem()
        if item is None:
            return
        self.controller.remove_game(item.text())
        self._fill_settings()
        self._refresh_game_note()

    def _refresh_game_note(self) -> None:
        settings = self.controller.settings
        if not settings.auto_game_mode:
            text = "Auto game mode is off."
        elif not settings.game_processes:
            text = "Auto game mode is on, but you have not added a program yet."
        else:
            text = "Watching for: " + ", ".join(settings.game_processes)
        self.window.home.game_note.setText(text)

    def _fill_settings(self) -> None:
        page = self.window.settings_page
        toggles = (page.autostart, page.on_top, page.auto_game, page.quit_off)
        for toggle in toggles:
            toggle.blockSignals(True)
        page.fill(self.controller.settings, self.controller.data_folder())
        for toggle in toggles:
            toggle.blockSignals(False)

    def _apply_hotkeys(self, emergency: str, power_on: str) -> None:
        try:
            notes = self.controller.set_hotkeys(emergency, power_on, self.registrar)
        except HotkeyError as exc:
            self.window.settings_page.hotkey_note.setText(str(exc))
            return
        if notes:
            self.window.settings_page.hotkey_note.setText(" ".join(notes))
        elif sys.platform == "win32":
            self.window.settings_page.hotkey_note.setText(
                f"Emergency stop is {emergency}. Turn on is {power_on}."
            )
        else:
            self.window.settings_page.hotkey_note.setText(
                "Global keys work on Windows. Here, use the buttons in the window."
            )

    def _on_hotkey_id(self, hotkey_id: int) -> None:
        if hotkey_id == EMERGENCY_ID:
            self.controller.turn_off(emergency=True)
        elif hotkey_id == POWER_ON_ID:
            self._turn_on()

    def _popup_menu(self, point) -> None:
        menu = QMenu()
        self._fill_menu(menu)
        menu.exec(point)

    def _fill_menu(self, menu: QMenu) -> None:
        menu.clear()
        state = self.controller.state
        menu.addAction("Open Home", self.show_window)
        if state in {"on", "game"}:
            menu.addAction("Turn AI off", lambda: self.controller.turn_off())
        else:
            menu.addAction("Turn AI on", self._turn_on)
        if state == "game":
            menu.addAction("Wake the model", self.controller.wake)
        elif state == "on":
            menu.addAction("Game mode", self.controller.enter_game)
        menu.addAction("Emergency stop", lambda: self.controller.turn_off(emergency=True))
        top = menu.addAction("Keep orb on top")
        top.setCheckable(True)
        top.setChecked(self.controller.settings.orb_always_on_top)
        top.triggered.connect(self._menu_on_top)
        menu.addSeparator()
        menu.addAction("Quit", self._quit)

    def _menu_on_top(self, checked: bool) -> None:
        self.window.settings_page.on_top.setChecked(checked)

    def _tray_activated(self, reason) -> None:
        if reason == self.tray.icon.ActivationReason.Trigger:
            self.show_window()

    def _place_orb(self) -> None:
        screen = self.window.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = self.controller.settings.orb_x
        y = self.controller.settings.orb_y
        orb_rect = QRect(x or -1, y or -1, self.orb.width(), self.orb.height())
        if x is None or y is None or not area.intersects(orb_rect):
            x = area.right() - self.orb.width() - 24
            y = area.bottom() - self.orb.height() - 24
        self.orb.move(x, y)

    def _toggle_expand(self) -> None:
        expanded = not self.controller.settings.window_expanded
        self.controller.settings.window_expanded = expanded
        save_settings(self.controller.settings)
        self.window.set_expanded(expanded)

    def _set_quit_off(self, on: bool) -> None:
        self.controller.settings.quit_turns_ai_off = bool(on)
        save_settings(self.controller.settings)

    def _ptt_tick(self) -> None:
        """Mouse button 4 (the side button). Polling does not swallow the click."""
        if sys.platform != "win32":
            return
        down = bool(ctypes.windll.user32.GetAsyncKeyState(0x05) & 0x8000)
        if not down:
            self._ptt_latched = False
            if getattr(self, "_holding", False) and getattr(self, "_hold_from_mouse", False):
                self._hold_from_mouse = False
                self._hold_up()
            return
        if getattr(self, "_ptt_latched", False) or getattr(self, "_holding", False):
            return
        if self.controller.state not in {"on", "off", "starting", "game"}:
            return
        self._hold_from_mouse = True
        self._hold_down()
        if not getattr(self, "_holding", False):
            self._ptt_latched = True

    def _hold_down(self) -> None:
        if getattr(self, "_holding", False):
            return
        if getattr(self, "_speaking", False) or (
            getattr(self, "_ask_job", None) is not None and self._ask_job.isRunning()
        ):
            self._cut_off()
        speaker.stop()
        stop_kokoro()
        if getattr(self, "_listener", None) is not None:
            self._listener.stop()
        if self.controller.state == "off" and not self.controller._busy:
            self.controller.turn_on()
        if self.controller.state not in {"on", "off", "starting", "game"}:
            self.window.home.set_reply(
                "nothing",
                "The AI is off.",
                "The microphone stays closed.",
            )
            return
        self._holding = True
        self._recording = False
        self.orb.set_state("listening", "Listening. Release to stop.")
        if packages_installed() and model_ready():
            try:
                self._recorder.start()
                self._recording = True
                self.window.home.set_phase("listening", "The microphone is open only while you hold.")
            except HearingError as exc:
                self._holding = False
                self._recorder.close()
                self.window.home.set_reply("nothing", "The microphone did not open.", str(exc))
                self.orb.set_state(self.controller.state, "Hold to talk")
            return
        self.window.home.set_phase(
            "listening",
            "Release to stop. Speech recognition still needs a download from the Voice tab.",
        )

    def _hold_up(self) -> None:
        if not getattr(self, "_holding", False):
            return
        self._holding = False
        self._clock = TurnClock()
        wav = b""
        if getattr(self, "_recording", False):
            self._recording = False
            try:
                wav = self._recorder.stop()
            except Exception:
                self._recorder.close()
                wav = b""
        if not packages_installed() or not model_ready():
            self.orb.set_state(self.controller.state, "Hold to talk")
            self.window.home.set_phase(self.controller.state, "The microphone stays closed until you hold to talk.")
            self._pending_line = ""
            self.window.home.set_reply(
                "(no words yet)",
                "I didn't hear words.",
                "Open the Voice tab and click Download speech recognition. Nothing was sent.",
            )
            self._sync_keyword()
            return
        self.orb.set_state("thinking", "Turning speech into text on this PC.")
        self.window.home.set_phase("thinking", "The microphone is closed. Nothing has been sent yet.")
        job = _HearJob(wav)
        self._hear_job = job
        job.heard.connect(self._heard)
        job.failed.connect(self._hear_failed)
        job.start()

    def _heard(self, text: str) -> None:
        if getattr(self, "_listener", None) is not None:
            self._listener.stop()
        text = (text or "").strip()
        if not text:
            self.window.home.set_reply("(nothing caught)", "I didn't catch that.", "Nothing was sent.")
            self.orb.set_state(self.controller.state, "Say the keyword")
            self._sync_keyword()
            return
        clock = getattr(self, "_clock", None)
        if clock is None or "first_sound" in clock.marks or "interrupt" in clock.marks:
            self._clock = TurnClock()
        self._clock.mark("transcript")
        quick = match_quick_command(text)
        if quick is not None and quick.kind == "undo":
            self._undo_timer()
            return
        if getattr(self, "_offer_load", False) and more_answer(text) == "yes":
            self._offer_load = False
            self._return_to_game = True
            self._close_followup()
            self.controller.wake()
            self.window.home.set_phase("on", "Loading the model. It unloads again two minutes after the answer.")
            return
        if self._followup_left > 0 and followup_phrase(text) == "":
            self._close_followup()
            self.window.home.set_phase("on", "Okay. I'm here when you need me.")
            return
        if (is_resume(text) or more_answer(text) == "yes" or followup_phrase(text) in {"tell me more", "read the rest"}) and (
            getattr(self, "_unheard", "") or getattr(self, "_more_text", "")
        ):
            rest = getattr(self, "_unheard", "") or getattr(self, "_more_text", "")
            self._unheard = ""
            self._more_text = ""
            self._close_followup()
            if self._history and self._history[-1].get("role") == "assistant":
                self._history[-1]["content"] = (self._history[-1]["content"] + " " + rest).strip()
            self.window.home.set_reply(text, rest, getattr(self, "_full_reply", rest))
            self._speak(rest)
            return
        if self._followup_left > 0:
            self._close_followup()
        if getattr(self, "_awaiting_more", False):
            answer = more_answer(text)
            if answer == "yes":
                self._read_the_rest()
                return
            if answer == "no":
                self._decline_more()
                return
            self._clear_more()
        self._pending_line = text
        self.window.home.set_reply(text, "Sending it to the model on this PC.", "")
        if text.lower().startswith("remind"):
            self._on_command(text)
            return
        self._send_heard()

    def _hear_failed(self, message: str) -> None:
        self.window.home.set_reply("(no words yet)", "I didn't hear words.", message)
        self.orb.set_state(self.controller.state, "Say the keyword")
        self._sync_keyword()

    def _show_keyword(self) -> None:
        settings = self.controller.settings
        button = self.window.home.keyword_button
        edit = self.window.home.keyword_edit
        button.blockSignals(True)
        edit.blockSignals(True)
        button.setChecked(settings.keyword_listening)
        button.setText("Listening for the keyword" if settings.keyword_listening else "Listen for a keyword")
        edit.setText(settings.keyword)
        button.blockSignals(False)
        edit.blockSignals(False)

    def _save_keyword(self) -> None:
        try:
            word = clean_keyword(self.window.home.keyword_edit.text())
        except KeywordError as exc:
            show_copyable(self.window, "That keyword was not saved", str(exc))
            self.window.home.keyword_edit.setText(self.controller.settings.keyword)
            return
        self.controller.settings.keyword = word
        save_settings(self.controller.settings)
        if self._listener.running:
            self._listener.stop()
        self._sync_keyword()

    def _toggle_keyword(self, on: bool) -> None:
        self.controller.settings.keyword_listening = bool(on)
        save_settings(self.controller.settings)
        self._show_keyword()
        if on and not (keyword_packages_installed() and keyword_model_ready()):
            self._download_keyword()
            return
        self._sync_keyword()

    def _download_keyword(self) -> None:
        agreed = ask_yes_no(
            self.window,
            "Listen for a keyword?",
            "The microphone stays open while this is on, so BabySitter can hear the keyword. "
            "The sound is checked on this PC. It is not saved and it is not sent. "
            "The first time also downloads a small model onto this PC.\n\n"
            f"The keyword is “{self.controller.settings.keyword}”.",
            "Turn listening on",
            "Leave the microphone closed",
        )
        if not agreed:
            self.controller.settings.keyword_listening = False
            save_settings(self.controller.settings)
            self._show_keyword()
            self.window.home.set_phase("on", "Keyword listening is off. The microphone is closed.")
            return
        job = _KeywordDownloadJob()
        self._keyword_job = job
        self.window.home.set_phase("on", "Downloading the keyword model onto this PC.")
        job.succeeded.connect(self._keyword_downloaded)
        job.failed.connect(self._keyword_download_failed)
        job.start()

    def _keyword_downloaded(self, message: str) -> None:
        self.window.home.set_phase("on", message)
        self._sync_keyword()

    def _keyword_download_failed(self, message: str) -> None:
        self.controller.settings.keyword_listening = False
        save_settings(self.controller.settings)
        self._show_keyword()
        self.window.home.set_phase("on", message)

    def _sync_keyword(self) -> None:
        if getattr(self, "_listener", None) is None:
            return
        busy = getattr(self, "_speaking", False) or getattr(self, "_holding", False)
        settings = self.controller.settings
        ready = keyword_packages_installed() and keyword_model_ready()
        if not busy and settings.keyword_listening and self.controller.state == "on" and ready:
            try:
                self._listener.start(
                    settings.keyword,
                    self._keyword_hub.phrase.emit,
                    self._keyword_hub.status.emit,
                    self._keyword_hub.failed.emit,
                )
            except KeywordError as exc:
                self._keyword_failed(str(exc))
            return
        self._listener.stop()

    def _keyword_status(self, status: str) -> None:
        word = self.controller.settings.keyword
        if status == "capturing":
            self.orb.set_state("listening", "Listening to the question.")
            self.window.home.set_phase("listening", "Say the question now. The microphone is open.")
            return
        if getattr(self, "_followup_left", 0) > 0:
            self._show_followup()
            return
        if getattr(self, "_awaiting_more", False):
            self.orb.set_state("on", "Say yes or no")
            self.window.home.set_phase(
                "on",
                "Say yes to hear the rest, or no to stop there. "
                f"A new question still starts with {word}.",
            )
            return
        self.orb.set_state("on", f"Say {word}")
        self.window.home.set_phase(
            "on",
            f"Say “{word}” and the command in one sentence. "
            "For example: baby sitter what time is it. The sound stays on this PC and is not saved.",
        )

    def _keyword_failed(self, message: str) -> None:
        self._listener.stop()
        self.controller.settings.keyword_listening = False
        save_settings(self.controller.settings)
        self._show_keyword()
        self.window.home.set_phase("on", message)

    def _on_command(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.window.home.set_reply("nothing", "Type something first.", "Nothing was sent.")
            return
        if getattr(self, "_awaiting_more", False):
            answer = more_answer(text)
            if answer == "yes":
                self.window.home.typed.clear()
                self._read_the_rest()
                return
            if answer == "no":
                self.window.home.typed.clear()
                self._decline_more()
                return
            self._clear_more()
        self.window.home.typed.clear()
        self._pending_line = text
        self.window.home.set_reply(text, "Waiting.", "Nothing has been sent yet.")
        if text.lower().startswith("remind"):
            if not ask_yes_no(
                self.window,
                "Save this reminder?",
                f"This stays on this PC. Nothing is sent out.\n\n{text}",
                "Save the reminder",
                "Don't save",
            ):
                self.window.home.set_reply(text, "Not saved.", "Nothing was sent.")
                return
            add_item("schedule.json", text=text)
            self.window.schedule_page.refresh()
            self.window.home.set_reply(text, "Saved on this PC.", "Nothing was sent off this computer.")
            return

    def _send_heard(self) -> None:
        text = getattr(self, "_pending_line", "").strip()
        if not text:
            self.window.home.set_reply("nothing", "Type a line first.", "Nothing was sent.")
            return
        if self._run_quick(text):
            return
        if self.controller.state == "game":
            self._offer_load = True
            self._close_followup()
            self._speak("I'm in Game mode. Load the brain? It needs about 8 GB of video memory.")
            return
        if self.controller.state != "on":
            if self.controller.state in {"off", "starting"} or self.controller._busy:
                self._queued_after_load = text
                self.window.home.set_reply(text, "Loading the model. I'll send this when it says On.", "Nothing was sent yet.")
                if self.controller.state == "off" and not self.controller._busy:
                    self.controller.turn_on()
                return
            self.window.home.set_reply(text, "The AI is off.", "Turn it on first. Nothing was sent.")
            return
        running = getattr(self, "_ask_job", None)
        if running is not None and running.isRunning() and not running.cancel.is_set():
            self.window.home.set_reply(text, "Still thinking.", "Wait for this reply to finish.")
            return
        mode = get_mode(self.controller.settings.intelligence)
        self._early_lead = ""
        self._pending_offer = ""
        self._finished_phrases = []
        self._logged_turn = False
        self._turn_id += 1
        if getattr(self, "_clock", None) is None:
            self._clock = TurnClock()
        self._clock.mark("transcript")
        self._filler.start(1500)
        note = getattr(self, "_interrupt_note", "")
        if note:
            text = f"{note}\n{text}"
            self._interrupt_note = ""
        alive = "2m" if getattr(self, "_return_to_game", False) else -1
        job = _AskJob(self.controller.ollama, mode.model, text, mode.num_ctx, self._history, keep_alive=alive)
        job.turn = self._turn_id
        self._ask_job = job
        job.measured.connect(lambda stats, turn=job.turn: self._on_measured(stats, turn))
        job.first_token.connect(lambda turn=job.turn: self._on_first_token(turn))
        job.lead_ready.connect(lambda lead, turn=job.turn: self._lead_ready(lead, turn))
        job.succeeded.connect(lambda reply, turn=job.turn: self._asked(reply, turn))
        job.failed.connect(lambda message, heard=text, turn=job.turn: self._ask_failed(heard, message, turn))
        self.orb.set_state("thinking", "Thinking.")
        self.window.home.set_phase("thinking", "Asking the model on this PC.")
        job.start()

    def _same_turn(self, turn: int) -> bool:
        return turn == getattr(self, "_turn_id", 0)

    def _on_measured(self, stats: dict, turn: int) -> None:
        if not self._same_turn(turn) or getattr(self, "_clock", None) is None:
            return
        for key in ("prompt_tokens", "gen_tokens", "prompt_tps", "gen_tps", "load_ms", "image_tokens"):
            value = stats.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                self._clock.marks[key] = value

    def _on_first_token(self, turn: int) -> None:
        if not self._same_turn(turn) or getattr(self, "_clock", None) is None:
            return
        self._clock.mark("first_token")

    def _cue_waiting(self) -> None:
        clock = getattr(self, "_clock", None)
        if clock is None or "first_sound" in clock.marks or not self._same_turn(self._turn_id):
            return
        line = ("One moment.", "Still working.", "Give me a second.")[self._filler_n % 3]
        self._filler_n += 1
        self.window.home.set_phase("thinking", line)
        self.orb.set_state("thinking", line)
        if kokoro_ready() and not getattr(self, "_speaking", False):
            self._speak(line, filler=True)

    def _cut_off(self) -> None:
        started = time.perf_counter()
        self._turn_id += 1
        self._filler.stop()
        job = getattr(self, "_ask_job", None)
        if job is not None:
            job.cancel.set()
        stop_kokoro()
        speaker.stop()
        heard = " ".join(getattr(self, "_finished_phrases", []))
        full = getattr(self, "_spoken_for_history", "") or getattr(self, "_full_reply", "") or getattr(self, "_early_lead", "")
        self._unheard = remainder_after(heard, full) if heard else full
        self._interrupt_note = interrupt_note(heard)
        self._remember_exchange(getattr(self, "_pending_line", ""), heard)
        self.controller._remember(heard or "Interrupted before a full phrase.")
        clock = getattr(self, "_clock", None)
        if clock is not None:
            clock.marks["interrupt"] = max(0, int((time.perf_counter() - started) * 1000))
            self._responsiveness.add(clock.as_row())
            self.window.voice_page.set_responsiveness(self._responsiveness.summary())
        self._speaking = False
        self._finished_phrases = []
        self.window.home.set_phase("on", "Stopped. Say carry on to hear the rest.")

    def _ask_failed(self, heard: str, message: str, turn: int = 0) -> None:
        if turn and not self._same_turn(turn):
            return
        self._filler.stop()
        self._pending_offer = ""
        self.window.home.set_reply(heard, "The model did not answer.", message)
        self._speaking = False
        self._sync_keyword()

    def _lead_ready(self, lead: str, turn: int = 0) -> None:
        """Speak the first sentence while the rest is still being written."""
        if turn and not self._same_turn(turn):
            return
        if getattr(self, "_clock", None) is not None:
            self._clock.mark("first_phrase")
        if getattr(self, "_early_lead", ""):
            return
        self._early_lead = lead
        heard = getattr(self, "_pending_line", "")
        self.window.home.set_reply(heard, lead, "Still writing the rest on this PC.")
        self._speak(lead)

    def _asked(self, reply: str, turn: int = 0) -> None:
        if turn and not self._same_turn(turn):
            return
        early = getattr(self, "_early_lead", "")
        spoken, rest = voice_and_rest(reply)
        spoken = spoken or early or "I don't have an answer for that."
        self._last_reply = (spoken[:80] or "Reply", reply)
        self._full_reply = reply
        self._spoken_for_history = spoken
        heard = getattr(self, "_pending_line", "")
        self._more_text = rest
        self._awaiting_more = False
        if getattr(self, "_listener", None) is not None:
            self._listener.expect_yes_no(False)
        self.window.home.set_reply(heard, spoken, reply)
        if early:
            self._early_lead = ""
            bare = early[:-1].rstrip() if early[-1:] in ".!?" else early
            extra = ""
            if bare and spoken.startswith(bare):
                extra = spoken[len(bare) :].lstrip(" \t,")
            if extra:
                self._pending_offer = extra
            return
        self._speak(spoken)

    def _clear_more(self) -> None:
        self._awaiting_more = False
        self._more_text = ""
        if getattr(self, "_listener", None) is not None:
            self._listener.expect_yes_no(False)

    def _decline_more(self) -> None:
        self._clear_more()
        self.window.home.set_phase("on", "Okay. I'll stop there.")
        self.orb.set_state(self.controller.state, "Say the keyword")
        self._sync_keyword()

    def _read_the_rest(self) -> None:
        rest = getattr(self, "_more_text", "")
        self._clear_more()
        if not rest:
            self.window.home.set_phase("on", "There isn't any more to read.")
            self._sync_keyword()
            return
        heard = getattr(self, "_pending_line", "")
        self.window.home.set_reply(heard, rest, getattr(self, "_full_reply", rest))
        self._speak(rest)

    def _pin_reply(self) -> None:
        last = getattr(self, "_last_reply", None)
        if not last:
            self.window.home.set_reply("nothing", "Nothing to pin yet.", "Send a reply first, or save a reminder.")
            return
        title, body = last
        add_item("pins.json", title=title, body=body)
        self._refresh_pins()
        self.window.home.set_reply(title, "Pinned.", "The card stays on this PC.")

    def _copy_reply(self) -> None:
        QApplication.clipboard().setText(self.window.home.reply_detail.text())
        self.controller._remember("Copied the reply.")
        self.window.home.set_history(self.controller.history)

    def _copy_log(self) -> None:
        QApplication.clipboard().setText(self.window.home.recent.toPlainText())
        self.controller._remember("Copied what just happened.")
        self.window.home.set_history(self.controller.history)

    def _choose_hero(self) -> None:
        path, _chosen = QFileDialog.getOpenFileName(
            self.window,
            "Choose a picture",
            "",
            "Pictures (*.png *.jpg *.jpeg *.webp)",
        )
        if not path:
            return
        data = Path(path).read_bytes()
        if len(data) > 15_000_000:
            show_copyable(self.window, "That picture is too large", "Choose one under 15 MB. Nothing was copied.")
            return
        hero_path().write_bytes(data)
        self.window.home.set_hero(str(hero_path()))
        self.controller._remember("Saved your picture in the BabySitter folder. It was not uploaded.")
        self.window.home.set_history(self.controller.history)

    def _on_page_notice(self, text: str) -> None:
        if text.startswith("CONFIRM reminder:"):
            body = text.split(":", 1)[1].strip()
            if ask_yes_no(self.window, "Save this reminder?", body, "Save the reminder", "Don't save"):
                add_item("schedule.json", text=body)
                self.window.schedule_page.text.clear()
                self.window.schedule_page.refresh()
            return
        if text.startswith("CONFIRM memory:"):
            body = text.split(":", 1)[1].strip()
            if ask_yes_no(
                self.window,
                "Remember this?",
                f"Save this on this PC?\n\n{body}",
                "Remember it",
                "Don't save",
            ):
                add_item("memory.json", text=body)
                self.window.memory_page.text.clear()
                self.window.memory_page.refresh()
            return
        if text == "CONFIRM screen":
            self._look_at_screen()
            return
        if text == "RUN health":
            self._read_health()
            return
        if text == "LIST models":
            self._list_models()
            return
        if text == "INSTALL hearing":
            self._install_hearing()
            return
        if text == "PREVIEW voice":
            self._preview_voice()
            return
        if text == "EXPORT timings":
            self._export_timings()
            return
        if text == "BENCHMARK":
            self._benchmark()
            return
        if text.startswith("FOLLOWUP "):
            self._save_followup(text)
            return
        self.controller._remember(text)
        self.window.home.set_history(self.controller.history)

    def _arm_game_return(self) -> None:
        if not getattr(self, "_return_to_game", False) or self.controller.state != "on":
            return
        timer = getattr(self, "_game_return_timer", None)
        if timer is None:
            timer = QTimer(self.window)
            timer.setSingleShot(True)
            timer.timeout.connect(self._return_game_now)
            self._game_return_timer = timer
        timer.start(120_000)

    def _return_game_now(self) -> None:
        self._return_to_game = False
        if self.controller.state == "on":
            self.controller.enter_game()

    def _look_at_screen(self, full: bool = False) -> None:
        if not ask_yes_no(
            self.window,
            "Look at the screen?",
            "BabySitter will take one picture in memory and ask the model that is already loaded. "
            + (
                "Small text is sent at full size, so this takes a few seconds. "
                if full
                else "The long edge is shrunk to 1280 pixels. "
            )
            + "The picture is not saved.",
            "Look now",
            "Don't look",
        ):
            self.window.screen_page.body.setPlainText("Nothing was captured.")
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            self.window.screen_page.body.setPlainText("No screen was found. Nothing was saved.")
            return
        picture = screen.grabWindow(0)
        if full:
            self.window.home.set_phase("thinking", "This takes a few seconds.")
        else:
            width, height = scaled_size(picture.width(), picture.height())
            if (width, height) != (picture.width(), picture.height()):
                picture = picture.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        encoded = _png_base64(picture)
        tokens = image_tokens(picture.width(), picture.height())
        self.window.screen_page.body.setPlainText(
            f"Captured and shrank the picture to {picture.width()} by {picture.height()} pixels in memory. "
            "It was not saved to disk."
        )
        del picture
        if self.controller.state != "on":
            self.window.screen_page.body.append("\nTurn the AI on before asking about the screen. Nothing was sent.")
            return
        self.window.home.set_phase("thinking", "Looking at the screen.")
        self._speak("Looking at the screen.", filler=True)
        self._pending_line = "What is on the screen?"
        mode = get_mode(self.controller.settings.intelligence)
        self._early_lead = ""
        self._pending_offer = ""
        self._finished_phrases = []
        self._logged_turn = False
        self._turn_id += 1
        if getattr(self, "_clock", None) is None:
            self._clock = TurnClock()
        self._clock.mark("transcript")
        text = "What is on this screen? Answer in two or three plain sentences."
        if getattr(self, "_clock", None) is not None:
            self._clock.marks["image_tokens"] = tokens
        alive = "2m" if getattr(self, "_return_to_game", False) else -1
        job = _AskJob(
            self.controller.ollama,
            mode.model,
            text,
            mode.num_ctx,
            self._history,
            [encoded],
            keep_alive=alive,
        )
        job.turn = self._turn_id
        self._ask_job = job
        job.measured.connect(lambda stats, turn=job.turn: self._on_measured(stats, turn))
        job.first_token.connect(lambda turn=job.turn: self._on_first_token(turn))
        job.lead_ready.connect(lambda lead, turn=job.turn: self._lead_ready(lead, turn))
        job.succeeded.connect(lambda reply, turn=job.turn: self._asked(reply, turn))
        job.failed.connect(lambda message, heard=text, turn=job.turn: self._ask_failed(heard, message, turn))
        self.orb.set_state("thinking", "Looking.")
        job.start()

    def _read_health(self) -> None:
        if sys.platform != "win32":
            self.window.health_page.body.setPlainText(
                "These checks run on your Windows PC. They are read-only. "
                "This computer is not Windows, so nothing was run and nothing was changed."
            )
            return
        import subprocess

        from babysitter.platform import run_hidden

        script = (
            "Write-Output '--- Memory ---'; "
            "Get-Process | Sort-Object WorkingSet64 -Descending | "
            "Select-Object -First 15 Name, @{n='MB';e={[math]::Round($_.WorkingSet64/1MB)}} | "
            "Format-Table -AutoSize | Out-String; "
            "Write-Output '--- Startup ---'; "
            "Get-CimInstance Win32_StartupCommand | Select-Object Name, Command, Location | "
            "Format-Table -AutoSize | Out-String; "
            "Write-Output '--- RAM ---'; "
            "Get-CimInstance Win32_PhysicalMemory | "
            "Select-Object PartNumber, Capacity, ConfiguredClockSpeed | Format-Table -AutoSize | Out-String"
        )
        try:
            completed = run_hidden(
                ["powershell", "-NoProfile", "-Command", script],
                timeout=40,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.window.health_page.body.setPlainText(f"The check could not run ({exc}). Nothing was changed.")
            return
        text = ((completed.stdout or "") + (completed.stderr or "")).strip()
        self.window.health_page.body.setPlainText(text or "The check returned nothing. Nothing was changed.")

    def _list_models(self) -> None:
        try:
            names = self.controller.ollama.installed_models()
        except OllamaError as exc:
            self.window.models_page.body.setPlainText(str(exc))
            return
        if not names:
            self.window.models_page.body.setPlainText("Ollama reported no installed models.")
            return
        self.window.models_page.body.setPlainText("\n".join(names))

    def _voice_prefs(self) -> dict:
        path = data_dir() / "voice.json"
        saved: dict = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    saved = loaded
            except (OSError, json.JSONDecodeError):
                saved = {}
        name = str(saved.get("voice") or "Heart & Sarah blend")
        try:
            speed = int(saved.get("speed") or 105)
        except (TypeError, ValueError):
            speed = 105
        try:
            pitch = int(saved.get("pitch") or -1)
        except (TypeError, ValueError):
            pitch = -1
        if name.startswith("Microsoft"):
            return {
                "engine": "windows",
                "name": name,
                "windows_voice": name,
                "speed": speed,
                "pitch": pitch,
                "rate": sapi_rate(speed),
                "label": name,
            }
        return {
            "engine": "kokoro",
            "name": name,
            "speed": speed,
            "pitch": pitch,
            "label": "Heart and Sarah" if "blend" in name.lower() or "sarah" in name.lower() else name,
        }

    def _speak(self, text: str, filler: bool = False) -> None:
        self._is_filler = filler
        stop_kokoro()
        speaker.stop()
        self._speaking = True
        self._pending_speech = text
        if getattr(self, "_listener", None) is not None:
            self._listener.stop()
        prefs = self._voice_prefs()
        if filler and prefs["engine"] == "kokoro" and not kokoro_ready():
            self._is_filler = False
            self._speaking = False
            return
        if prefs["engine"] == "kokoro" and not kokoro_ready():
            self._offer_kokoro()
            return
        if prefs["engine"] == "windows" and sys.platform != "win32":
            self._speaking = False
            self._sync_keyword()
            return
        self._start_speech(text, prefs)

    def _offer_kokoro(self) -> None:
        agreed = ask_yes_no(
            self.window,
            "Download Heart and Sarah?",
            "The voice you picked is Heart and Sarah. It is not on this PC yet, "
            "so the reply was spoken with a Windows voice instead. "
            "Downloading keeps that voice on this PC. It uses the processor, not the graphics card.",
            "Download Heart and Sarah",
            "Not now",
        )
        if not agreed:
            self._speaking = False
            self.window.home.set_phase(
                "on",
                "Heart and Sarah is not downloaded, so nothing was spoken with that voice.",
            )
            self._sync_keyword()
            return
        job = _KokoroDownloadJob()
        self._kokoro_job = job
        self.window.home.set_phase("on", "Downloading Heart and Sarah onto this PC. This can take a few minutes.")
        job.succeeded.connect(self._kokoro_ready)
        job.failed.connect(self._kokoro_failed)
        job.start()

    def _kokoro_ready(self, _message: str) -> None:
        text = getattr(self, "_pending_speech", "")
        self._start_speech(text, self._voice_prefs())

    def _kokoro_failed(self, message: str) -> None:
        self._speaking = False
        self.window.home.set_phase("on", message)
        self._sync_keyword()

    def _start_speech(self, text: str, prefs: dict) -> None:
        if not text:
            self._speaking = False
            self._sync_keyword()
            return
        job = _SpeakJob(text, prefs, self._turn_id)
        self._speak_job = job
        self.orb.set_state("speaking", text)
        self.window.home.set_phase("speaking", f"Speaking with {prefs['label']}.")
        job.started.connect(self._sound_started)
        job.phrase_done.connect(self._phrase_finished)
        job.failed.connect(self._speech_failed)
        job.finished.connect(self._speak_done)
        job.start()

    def _sound_started(self) -> None:
        self._filler.stop()
        clock = getattr(self, "_clock", None)
        if clock is None:
            return
        clock.mark("first_sound")
        self._responsiveness.add(clock.as_row())
        self.window.voice_page.set_responsiveness(self._responsiveness.summary())

    def _phrase_finished(self, phrase: str) -> None:
        if getattr(self, "_is_filler", False):
            return
        job = getattr(self, "_speak_job", None)
        if job is not None and job.turn != self._turn_id:
            return
        self._finished_phrases.append(phrase)

    def _speech_failed(self, message: str) -> None:
        self.window.home.set_phase(self.controller.state, message)

    def _speak_done(self) -> None:
        self._speaking = False
        if getattr(self, "_is_filler", False):
            self._is_filler = False
            return
        if getattr(self, "_pending_offer", ""):
            offer = self._pending_offer
            self._pending_offer = ""
            self._speak(offer)
            return
        self._remember_exchange(getattr(self, "_pending_line", ""), getattr(self, "_spoken_for_history", ""))
        self._arm_game_return()
        self._open_followup()

    def _remember_exchange(self, user: str, assistant: str) -> None:
        if getattr(self, "_logged_turn", False):
            return
        if not (user or assistant):
            return
        if user:
            self._history.append({"role": "user", "content": user})
        if assistant:
            self._history.append({"role": "assistant", "content": assistant})
        del self._history[:-12]
        self._logged_turn = True

    def _open_followup(self) -> None:
        settings = self.controller.settings
        listening = settings.keyword_listening and self.controller.state == "on"
        ready = keyword_packages_installed() and keyword_model_ready()
        if not listening or not ready or getattr(self, "_listener", None) is None:
            self.orb.set_state(self.controller.state, "Say the keyword")
            self._sync_keyword()
            return
        self._listener.expect_followup(True)
        self._followup_left = max(5, min(20, int(settings.followup_seconds)))
        self._follow_timer.start()
        self._sync_keyword()
        self._show_followup()

    def _follow_tick(self) -> None:
        self._followup_left -= 1
        if self._followup_left <= 0:
            self._close_followup()
            return
        self._show_followup()

    def _show_followup(self) -> None:
        left = self._followup_left
        self.orb.set_state("on", f"Follow-up {left}")
        self.window.home.set_phase(
            "on",
            f"Listening for a follow-up. {left} seconds. You do not need to say baby sitter. "
            "Say that's all to stop.",
        )

    def _close_followup(self) -> None:
        self._follow_timer.stop()
        self._followup_left = 0
        if getattr(self, "_listener", None) is not None:
            self._listener.expect_followup(False)
        self.orb.set_state(self.controller.state, "Say the keyword")
        self._sync_keyword()

    def _run_quick(self, text: str) -> bool:
        quick = match_quick_command(text)
        if quick is None or quick.kind == "undo":
            return False
        if quick.kind == "time":
            now = datetime.now().astimezone()
            speech = now.strftime("It's %A, %B %d, %I:%M %p.").replace(" 0", " ")
            self.window.home.set_reply(text, speech, "Read from this PC. The model was not asked.")
            self._speak(speech)
            return True
        if quick.kind == "vram":
            snap = getattr(self.controller, "latest_status", None)
            gpu = getattr(snap, "gpu", None) if snap is not None else None
            if gpu is None:
                speech = "I can't see the video memory from here."
                detail = "nvidia-smi did not report a card."
            else:
                speech = f"Video memory is using {gpu.used_mib:,} of {gpu.total_mib:,} megabytes."
                detail = "Read from this PC. The model was not asked."
            self.window.home.set_reply(text, speech, detail)
            self._speak(speech)
            return True
        if quick.kind == "health":
            self._read_health()
            speech = "The PC check is on the PC Health tab. I did not change anything."
            self.window.home.set_reply(text, speech, "Read only.")
            self._speak(speech)
            return True
        if quick.kind == "screen":
            self._look_at_screen()
            return True
        if quick.kind == "screen_text":
            self._look_at_screen(full=True)
            return True
        if quick.kind == "why":
            lines = []
            for item in self._history[-6:]:
                role = "You" if item.get("role") == "user" else "BabySitter"
                lines.append(f"{role}: {str(item.get('content') or '')[:240]}")
            detail = "\n".join(lines) if lines else "Nothing from this conversation was sent with the last reply."
            speech = "I used the recent conversation. It is on the screen. Saved facts are not sent to the model yet."
            self.window.home.set_reply(text, speech, detail)
            self._speak(speech)
            return True
        if quick.kind == "timer":
            self._begin_timer(quick.seconds)
            return True
        return False

    def _begin_timer(self, seconds: int) -> None:
        previous = getattr(self, "_active_timer", None)
        if previous is not None:
            previous.stop()
        label = timer_label(seconds)
        timer = QTimer(self.window)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._timer_finished(label))
        timer.start(seconds * 1000)
        self._active_timer = timer
        self._undo_until = time.time() + 10
        speech = f"Timer set for {label}. Say undo in the next 10 seconds to cancel it."
        self.window.home.set_reply("timer", speech, "It stays on this PC. It is not a calendar event.")
        self._speak(speech)

    def _undo_timer(self) -> None:
        if time.time() > getattr(self, "_undo_until", 0) or getattr(self, "_active_timer", None) is None:
            self._speak("Nothing to undo.")
            return
        self._active_timer.stop()
        self._active_timer = None
        self._undo_until = 0
        self.window.home.set_reply("undo", "Cancelled the timer.", "Nothing else was changed.")
        self._speak("Cancelled the timer.")

    def _timer_finished(self, label: str) -> None:
        self._active_timer = None
        self._undo_until = 0
        speech = f"Your {label} timer is done."
        self.window.home.set_reply("timer", speech, "Nothing was sent off this PC.")
        self._speak(speech)

    def _save_followup(self, text: str) -> None:
        try:
            seconds = int(text.split()[1])
        except (IndexError, ValueError):
            return
        seconds = max(5, min(20, seconds))
        self.controller.settings.followup_seconds = seconds
        save_settings(self.controller.settings)
        self.window.voice_page.status.setText(f"Follow-up listening is {seconds} seconds. Saved on this PC.")

    def _benchmark(self) -> None:
        if self.controller.state != "on":
            self.window.models_page.body.setPlainText("Turn the AI on before the benchmark. Nothing was sent.")
            return
        running = getattr(self, "_bench_job", None)
        if running is not None and running.isRunning():
            self.window.models_page.body.setPlainText("A benchmark is already running.")
            return
        mode = get_mode(self.controller.settings.intelligence)
        running_voice = getattr(self, "_ask_job", None)
        if running_voice is not None and running_voice.isRunning():
            self.window.models_page.body.setPlainText("A reply is in progress. The benchmark waits so it does not wipe that conversation.")
            return
        job = _BenchJob(self.controller.ollama, mode.model, mode.num_ctx)
        self._bench_job = job
        self.window.models_page.body.setPlainText("Timing a fixed prompt three times. Thinking is off. Words are not saved.")
        job.finished_text.connect(self._benchmark_done)
        job.start()

    def _benchmark_done(self, text: str) -> None:
        samples = list(getattr(self._bench_job, "samples", []) or [])
        speeds = [int(sample.get("gen_tps", 0)) for sample in samples if isinstance(sample, dict)]
        speeds = [speed for speed in speeds if speed > 0]
        warning = ""
        path = data_dir() / "benchmark.json"
        if speeds:
            typical = sorted(speeds)[(len(speeds) - 1) // 2]
            previous = 0
            if path.is_file():
                try:
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    previous = int(saved.get("gen_tps") or 0)
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    previous = 0
            else:
                path.write_text(json.dumps({"gen_tps": typical}) + "\n", encoding="utf-8")
            found = benchmark_warning(typical, previous)
            if found:
                warning = "\n" + found
        version = ""
        if self.controller.version and self.controller.version.version:
            version = " Ollama " + ".".join(str(part) for part in self.controller.version.version) + "."
        self.window.models_page.body.setPlainText(text + version + warning)

    def _export_timings(self) -> None:
        path = data_dir() / "diagnostics.txt"
        extra = [self._responsiveness.export_text().rstrip()]
        bench = data_dir() / "benchmark.json"
        if bench.is_file():
            extra.append("Benchmark: " + bench.read_text(encoding="utf-8").strip())
        snap = self.controller.latest_status
        if snap is not None and snap.gpu is not None:
            extra.append(f"Video memory {snap.gpu.used_mib} of {snap.gpu.total_mib} MB.")
        path.write_text("\n".join(extra) + "\n", encoding="utf-8")

        self.window.voice_page.set_responsiveness(self._responsiveness.summary())
        self.window.voice_page.status.setText(f"Saved timings on this PC: {path}")

    def _preview_voice(self) -> None:
        if sys.platform != "win32":
            self.window.voice_page.status.setText(
                "This computer is not Windows, so the preview stayed on screen: Fresh start, I kept the important bits."
            )
            return
        prefs = self._voice_prefs()
        self.window.voice_page.status.setText(f"Speaking with {prefs['label']}.")
        self._speak("Fresh start, I kept the important bits.")

    def _install_hearing(self) -> None:
        if packages_installed() and model_ready():
            self.window.voice_page.status.setText("Speech recognition is already on this PC. Hold Talk to use it.")
            return
        agreed = ask_yes_no(
            self.window,
            "Download speech recognition?",
            "This downloads the hearing programs and a small speech model onto this PC. "
            "They run on the processor, not the graphics card. Nothing you say is sent off this computer.",
            "Download",
            "Don't download",
        )
        if not agreed:
            self.window.voice_page.status.setText("Nothing was downloaded.")
            return
        job = _InstallHearingJob()
        self._install_job = job
        self.window.voice_page.status.setText("Downloading. This can take a few minutes. You can leave this window open.")
        job.succeeded.connect(self.window.voice_page.status.setText)
        job.failed.connect(lambda message: self.window.voice_page.status.setText(message))
        job.start()

    def _refresh_pins(self) -> None:
        self.window.set_pins(load_list("pins.json"))

    def _show_pin(self, pin_id: str) -> None:
        for pin in load_list("pins.json"):
            if pin.get("id") == pin_id:
                show_copyable(
                    self.window,
                    str(pin.get("title") or "Pinned"),
                    str(pin.get("body") or ""),
                )
                return

    def _quit(self) -> None:
        decision = self.controller.request_quit()
        if decision == "quit":
            self._finish_quit()
            return
        if decision == "wait":
            return
        choice = ask_three(
            self.window,
            "Quit BabySitter?",
            "The AI is not fully off. Stopping Ollama unloads the model and closes the server "
            "BabySitter is using.",
        )
        if choice == "stop":
            self.controller.quit_after_stopping()
        elif choice == "leave":
            self._finish_quit()

    def _finish_quit(self) -> None:
        try:
            self.registrar.clear()
        except OSError:
            pass
        self.controller.shutdown_threads()
        QApplication.quit()


def load_icon() -> QIcon:
    path = asset_path("icon.png")
    if path.is_file():
        return QIcon(str(path))
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#2dd4bf"))
    return QIcon(pixmap)


def open_folder(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))
