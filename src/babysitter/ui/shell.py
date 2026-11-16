"""Puts the window, the orb, and the tray on the same power switch."""

from __future__ import annotations

import base64
import ctypes
import json
import queue
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QBuffer, QEvent, QIODevice, QObject, QRect, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMenu

from babysitter.commands import match_quick_command, spoken_clock, timer_label
from babysitter.filefind import (
    CACHE_SECONDS,
    default_folders,
    match_files,
    open_found,
    recently_opened,
    scan_folders,
    search_reply,
)
from babysitter.games import foreground_process_name, should_hide_orb
from babysitter.journal import (
    day_detail,
    day_speech,
    finish_task,
    load_day,
    save_day,
    start_task,
    wipe as wipe_journal,
)
from babysitter.intents import guarded_prompt, match_tool
from babysitter.searx import SearxError, search as searx_search
from babysitter.sessions import append_turn, begin_session, delete_session, export_text
from babysitter.updates import UpdateError, check_latest
from babysitter.controller import Controller, windows_registrar_or_dummy
from babysitter.deskstore import add_item, hero_path, load_list, remove_item, save_list
from babysitter.intelligence import get_mode
from babysitter.ollama import IDLE_KEEP_ALIVE, OllamaError, classify_ollama_process
from babysitter.hotkeys import EMERGENCY_ID, POWER_ON_ID, HotkeyError
from babysitter.paths import asset_path, data_dir
from babysitter.pictures import benchmark_warning, fit_screenshot, image_tokens
from babysitter.embedder import rank_texts
from babysitter.personality import record as record_rating
from babysitter.personality import session_clause
from babysitter.proactivity import nudge, offer_more, weekly_review
from babysitter.turngate import TurnGate
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
    alert_voice,
    closed_lead,
    followup_phrase,
    interrupt_note,
    is_resume,
    lead_and_rest,
    more_answer,
    unread_detail,
    remainder_after,
    remembered_reply,
    sapi_rate,
    speech_chunks,
    strip_thinking,
    rest_after_lead,
    voice_and_rest,
)
from babysitter.responsiveness import ResponsivenessLog, TurnClock
from babysitter.plugins.voice.windows_voice import WindowsVoiceError, speaker
from babysitter.pcscan import (
    apply_startup,
    close_named,
    collect_processes,
    collect_startups,
    pids_named,
    scan,
    spoken_reading,
    suggestion_answer,
    terminate_pid,
    windows_startup_store,
)
from babysitter.plugins.tools.google_account import (
    GoogleError,
    GoogleReader,
    authorization_url,
    default_google_vault,
    exchange_code,
    fresh_lines,
    http_get_json,
    listen_for_code,
    pkce_pair,
    refresh_access,
)
from babysitter.plugins.voice.silero_model import SileroError, download_silero
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
    def __init__(self, busy) -> None:
        super().__init__()
        self._busy = busy

    def run(self) -> None:
        if self._busy():
            return
        try:
            from babysitter.embedder import warm as warm_embedder

            warm_embedder()
        except Exception:
            pass
        try:
            from babysitter.plugins.voice.kokoro_voice import ready, warm
            from babysitter.plugins.voice.fillers import library

            warm()
            if self._busy() or not ready():
                return

            def render(text: str):
                from babysitter.plugins.voice.kokoro_voice import render_clip

                return render_clip(text)

            library().prepare(render, self._busy)
        except Exception:
            return


def _png_base64(picture: QPixmap) -> str:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    picture.save(buffer, "PNG")
    return base64.b64encode(bytes(buffer.data())).decode("ascii")


class _BenchJob(QThread):
    finished_text = Signal(str)

    def __init__(self, ollama, model: str, num_ctx: int, num_batch: int = 512) -> None:
        super().__init__()
        self._ollama = ollama
        self._model = model
        self._num_ctx = num_ctx
        self._num_batch = num_batch

    def run(self) -> None:
        from babysitter.pictures import format_benchmark

        samples: list[dict] = []
        try:
            for _ in range(3):
                started = time.perf_counter()
                stats: dict = {}
                for _piece in self._ollama.iter_reply(
                    self._model,
                    "Reply with only the word ready.",
                    self._num_ctx,
                    num_batch=self._num_batch,
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

    def __init__(
        self,
        ollama,
        model: str,
        prompt: str,
        num_ctx: int,
        history=None,
        images=None,
        keep_alive=-1,
        num_batch: int = 512,
        facts=None,
        personality: str = "",
    ) -> None:
        super().__init__()
        self._ollama = ollama
        self._model = model
        self._prompt = prompt
        self._num_ctx = num_ctx
        self._history = list(history or [])
        self._images = images
        self._keep_alive = keep_alive
        self._num_batch = num_batch
        self._facts = list(facts or [])
        self._personality = personality
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
                self._num_batch,
                self._facts,
                self._personality,
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


class _EmbedderDownloadJob(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def run(self) -> None:
        from babysitter.embedder import EmbedderError, download as download_embedder

        try:
            message = download_embedder()
        except EmbedderError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        try:
            # Embed the facts already saved, here on this thread, so the
            # first question afterwards does not pay for all of them.
            from babysitter.embedder import rank_texts

            facts = [str(item.get("text") or "") for item in load_list("memory.json")]
            if facts:
                rank_texts("warming the cache", facts)
        except Exception:
            pass
        self.succeeded.emit(message)


class _FindJob(QThread):
    """Walks the chosen folders off the window's thread, so a slow disk
    or a cloud-backed Documents folder never freezes the app."""

    finished_scan = Signal(object)

    def __init__(self, folders: list[str]) -> None:
        super().__init__()
        self._folders = list(folders)

    def run(self) -> None:
        try:
            entries = scan_folders(self._folders)
            opened = recently_opened()
        except Exception:
            entries, opened = [], {}
        self.finished_scan.emit((entries, opened))


class _SpeakJob(QThread):
    started = Signal()
    phrase_done = Signal(str)
    failed = Signal(str)

    def __init__(self, text: str, prefs: dict, turn: int) -> None:
        super().__init__()
        self._text = text
        self._prefs = prefs
        self.turn = turn
        self.incoming: queue.Queue = queue.Queue()
        self._limit = 120 if prefs.get("engine") == "windows" else 220

    def add(self, text: str) -> None:
        """More sentences for the reply that is already being spoken."""
        for piece in speech_chunks(text, limit=self._limit):
            self.incoming.put(piece)

    def close_input(self) -> None:
        """No more sentences are coming. The voice finishes what it has."""
        self.incoming.put(None)

    def run(self) -> None:
        text = self._text
        self._text = ""
        prefs = self._prefs
        try:
            pieces = speech_chunks(text, limit=self._limit)
            if prefs.get("engine") == "windows":
                announced = False
                pending = list(pieces)
                while pending:
                    piece = pending.pop(0)
                    if speaker.cancelled.is_set():
                        break
                    if not announced:
                        self.started.emit()
                        announced = True
                    speaker.speak(piece, voice=prefs.get("windows_voice", ""), rate=prefs.get("rate", 0))
                    if speaker.cancelled.is_set():
                        break
                    self.phrase_done.emit(piece)
                    if not pending:
                        nxt = self.incoming.get()
                        if nxt is None:
                            break
                        pending.append(nxt)
            else:
                from babysitter.plugins.voice.kokoro_voice import speak_sequence

                speak_sequence(
                    pieces,
                    prefs.get("name", ""),
                    prefs.get("speed", 105),
                    prefs.get("pitch", -1),
                    on_start=self.started.emit,
                    on_piece=self.phrase_done.emit,
                    incoming=self.incoming,
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


class _GoogleJob(QThread):
    ready = Signal(str)

    def __init__(self, token: str, kind: str) -> None:
        super().__init__()
        self._token = token
        self._kind = kind

    def run(self) -> None:
        secret = self._token
        self._token = ""
        try:
            reader = GoogleReader(secret, http_get_json)
            if self._kind == "mail":
                speech = reader.unread()
            elif self._kind == "calendar":
                speech = reader.upcoming()
            else:
                speech = reader.unread() + " " + reader.upcoming()
        except GoogleError as exc:
            speech = str(exc)
        except Exception:
            speech = "Google did not answer. Mail and the calendar were not changed."
        if secret and secret in speech:
            speech = "Google did not answer. Mail and the calendar were not changed."
        secret = ""
        self.ready.emit(speech)


class _GooglePollJob(QThread):
    ready = Signal(str, list)

    def __init__(self, token: str, seen: set[str]) -> None:
        super().__init__()
        self._token = token
        self._seen = set(seen)

    def run(self) -> None:
        secret = self._token
        self._token = ""
        updated = set(self._seen)
        try:
            reader = GoogleReader(secret, http_get_json)
            mail_ids, mail_titles = reader.mail_index()
            event_ids, event_titles = reader.event_index()
            speech, updated = fresh_lines(
                list(mail_ids) + list(event_ids),
                list(mail_titles) + list(event_titles),
                self._seen,
            )
        except GoogleError as exc:
            speech = str(exc)
        except Exception:
            speech = "Google did not answer. Mail and the calendar were not changed."
        if secret and secret in speech:
            speech = "Google did not answer. Mail and the calendar were not changed."
        secret = ""
        self.ready.emit(speech, list(updated))


class _SignInJob(QThread):
    open_browser = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, client_id: str, verifier: str, state: str, url: str) -> None:
        super().__init__()
        self._client_id = client_id
        self._verifier = verifier
        self._state = state
        self._url = url
        self.bundle: dict | None = None

    def run(self) -> None:
        try:
            code = listen_for_code(self._state, on_ready=lambda: self.open_browser.emit(self._url))
            self.bundle = exchange_code(self._client_id, code, self._verifier)
            self.finished_ok.emit()
        except GoogleError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Google sign-in did not finish. Nothing was saved.")
        finally:
            self._verifier = ""


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
        self.window.title_icon.setPixmap(self.icon.pixmap(20, 20))
        self.tray = Tray(self.icon)
        self._orb_hidden_by_user = False
        self.registrar = windows_registrar_or_dummy()
        self.vault = default_vault()
        self.google_vault = default_google_vault()
        self._startup_store = windows_startup_store()
        self._suggestions: list = []
        self._suggestion_at = 0
        self._scan_prefix = ""
        self._scan_when_free = False
        self._soft_undo = None
        self._google_notified = False
        self._google_speak_errors = True
        self._session_id = ""
        self._pending_tool = None
        self._tool_summary = ""
        self._seen_google: set[str] = set()
        self._load_seen_google()
        self._google_poll = QTimer(self.window)
        self._google_poll.setInterval(15 * 60 * 1000)
        self._google_poll.timeout.connect(lambda: self._start_google("both", speak_errors=False, only_new=True))
        self._search_job: _SearchJob | None = None
        self._power_ready = False
        self._turn_id = 0
        self._responsiveness = ResponsivenessLog()
        self.turns = TurnGate()
        self._model_turn_open = False
        self._filler_stop = threading.Event()
        self._session_personality = ""
        self._weekly_offered = False
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
        self._show_mode("off", "The AI is off. Nothing is listening.")

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
        self.window.show_page(self.window.home)

    def _connect(self) -> None:
        home = self.window.home
        settings = self.window.settings_page
        home.power.clicked.connect(self._on_power)
        self.window.pill.clicked.connect(self._on_power)
        home.try_again.clicked.connect(self._turn_on)
        home.game.clicked.connect(self._on_game)
        self.window.emergency.clicked.connect(lambda: self.controller.turn_off(emergency=True))
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
        self.controller.game_offer.connect(self._offer_game)
        self.controller.quit_ready.connect(self._finish_quit)
        self.window.hidden_to_tray.connect(self._on_hidden_to_tray)
        settings.autostart.toggled.connect(self._set_autostart)
        settings.on_top.toggled.connect(self._set_on_top)
        settings.auto_game.toggled.connect(self._set_auto_game)
        settings.game_mode_ask.toggled.connect(self._set_game_ask)
        settings.detect_games.toggled.connect(self._set_detect_games)
        settings.off_game_cores.toggled.connect(self._set_core_avoidance)
        settings.vad_enabled.toggled.connect(lambda on: self._set_flag("vad_enabled", on))
        settings.smart_turn.toggled.connect(lambda on: self._set_flag("smart_turn", on))
        settings.echo_cancel.toggled.connect(lambda on: self._set_flag("echo_cancel", on))
        settings.talk_over.toggled.connect(lambda on: self._set_flag("talk_over", on))
        settings.hide_orb_for_games.toggled.connect(lambda on: self._set_flag("hide_orb_for_games", on))
        settings.quiet_hours.toggled.connect(lambda on: self._set_flag("quiet_hours", on))
        settings.side_button.toggled.connect(lambda on: self._set_flag("side_button", on))
        settings.searx_enabled.toggled.connect(lambda on: self._set_flag("searx_enabled", on))
        settings.quiet_save.clicked.connect(self._save_quiet_hours)
        settings.searx_save.clicked.connect(self._save_searx_port)
        settings.check_updates.clicked.connect(self._check_updates)
        self._hide_charts = _HideCharts(self.controller.probe)
        self.window.installEventFilter(self._hide_charts)
        settings.emergency_change.clicked.connect(self._change_emergency)
        settings.power_change.clicked.connect(self._change_power_key)
        settings.add_game.clicked.connect(self._add_running_game)
        settings.add_typed.clicked.connect(self._add_typed_game)
        settings.remove_game.clicked.connect(self._remove_game)
        self.window.journal_page.enabled.toggled.connect(self._set_journal_enabled)
        self.window.journal_page.notice.connect(self._on_page_notice)
        self.window.files_page.notice.connect(self._on_page_notice)
        settings.wipe_journal.clicked.connect(self._wipe_journal)
        settings.add_search_folder.clicked.connect(self._add_search_folder)
        settings.remove_search_folder.clicked.connect(self._remove_search_folder)
        settings.open_data.clicked.connect(lambda: open_folder(self.controller.data_folder()))
        settings.open_log.clicked.connect(lambda: open_folder(self.controller.log_folder()))
        tools = self.window.tools_page
        tools.enabled_changed.connect(self._set_social)
        tools.save_key.connect(self._save_social_key)
        tools.delete_key.connect(self._delete_social_key)
        tools.search_requested.connect(self._prepare_search)
        tools.google_enabled_changed.connect(self._set_google)
        tools.save_google.connect(self._save_google_token)
        tools.delete_google.connect(self._delete_google_token)
        tools.google_check.connect(self._google_from_button)
        tools.google_sign_in_requested.connect(self._google_sign_in)
        tools.google_client.setText(self.controller.settings.google_client_id)
        tools.set_enabled(self.controller.settings.social_search_enabled)
        tools.set_google_enabled(self.controller.settings.google_enabled)
        self._refresh_privacy()
        saved = self.vault.has_key() if self.vault.available else False
        tools.set_key_saved(saved, self.vault.available)
        saved_google = self.google_vault.has_token() if self.google_vault.available else False
        tools.set_google_saved(saved_google, self.google_vault.available)
        self.window.expanded_changed.connect(self._save_window_mode)
        self.window.set_expanded(self.controller.settings.window_expanded)
        self.window.pin_open.connect(self._show_pin)
        self.window.home.pin_unpin.connect(self._unpin_card)
        self.window.files_page.set_folders(self._search_places())
        self.window.journal_page.set_paused(bool(getattr(self.controller, "journal_paused", False)))
        home.hold_pressed.connect(self._hold_down)
        home.hold_released.connect(self._hold_up)
        home.command_submitted.connect(self._on_command)
        home.send_heard.connect(self._send_heard)
        home.pin_reply.connect(self._pin_reply)
        home.pin_note.connect(self._pin_note)
        home.copy_reply.connect(self._copy_reply)
        home.copy_log.connect(self._copy_log)
        home.choose_hero.connect(self._choose_hero)
        self.window.voice_page.notice.connect(self._on_page_notice)
        self.window.voice_page.followup[1].setValue(self.controller.settings.followup_seconds)
        self.window.voice_page.proactivity[1].setValue(self.controller.settings.proactivity)
        self.window.schedule_page.notice.connect(self._on_page_notice)
        for page in (
            self.window.schedule_page,
            self.window.memory_page,
            self.window.history_page,
            self.window.screen_page,
            self.window.health_page,
            self.window.models_page,
            self.window.journal_page,
            self.window.files_page,
            self.window.tools_page,
            self.window.voice_page,
            self.window.settings_page,
        ):
            page.pin_line.connect(self._pin_line)
        self.window.memory_page.notice.connect(self._on_page_notice)
        self.window.screen_page.notice.connect(self._on_page_notice)
        self.window.health_page.notice.connect(self._on_page_notice)
        self.window.models_page.notice.connect(self._on_page_notice)
        settings.quit_off.toggled.connect(self._set_quit_off)
        self._refresh_pins()
        if hero_path().is_file():
            self.window.home.set_hero(str(hero_path()))
        elif asset_path("hero.jpg").is_file():
            self.window.home.set_hero(str(asset_path("hero.jpg")))
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
        self._reminder_timer = QTimer(self.window)
        self._reminder_timer.setInterval(15000)
        self._reminder_timer.timeout.connect(self._check_reminders)
        self._reminder_timer.start()

    def _set_social(self, on: bool) -> None:
        self.controller.settings.social_search_enabled = bool(on)
        save_settings(self.controller.settings)
        self._refresh_privacy()

    def _set_google(self, on: bool) -> None:
        self.controller.settings.google_enabled = bool(on)
        save_settings(self.controller.settings)
        self._refresh_privacy()

    def _refresh_privacy(self) -> None:
        settings = self.controller.settings
        self.window.home.set_privacy(settings.social_search_enabled, settings.google_enabled)
        self.window.set_privacy(settings.social_search_enabled or settings.google_enabled)

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

    def _prepare_search(self, action_id: str, text: str, already_yes: bool = False) -> None:
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
        if not already_yes and not ask_yes_no(
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
        summary = getattr(self, "_tool_summary", "")
        self._tool_summary = ""
        if summary and self.controller.state == "on":
            self._pending_line = guarded_prompt(summary, detail[:2000])
            self._send_heard()

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

    def _show_mode(self, state: str, detail: str) -> None:
        """The frog, the state pill, and the tray all show the same mode.

        Listening, Thinking, and Speaking are not power states. The power
        switch stays where the controller left it.
        """
        self.orb.set_state(state, detail)
        word = STATE_WORDS.get(state, "Needs you")
        self.window.set_chip(state, word)
        self.tray.set_tooltip(f"BabySitter: {word}. {detail}")

    def _on_state(self, state: str, message: str) -> None:
        self.window.home.set_state(state, message)
        self.window.home.set_history(self.controller.history)
        self._show_mode(state, message)
        self.window.set_status_line(message)
        self._sync_keyword()
        if state == "off":
            release_model()
            release_kokoro()
            self._session_personality = ""
            self._google_notified = False
            self._session_id = ""
            self._google_poll.stop()
            self._end_model_turn()
            self._return_to_game = False
            timer = getattr(self, "_game_return_timer", None)
            if timer is not None:
                timer.stop()
        if state == "on":
            self._session_personality = session_clause()
            self._warm_voice()
            self._warm_hearing()
            self._arm_game_return()
            queued = getattr(self, "_queued_after_load", "")
            if queued:
                self._queued_after_load = ""
                self._pending_line = queued
                self._send_heard()
            elif self.controller.settings.google_enabled and not self._google_notified:
                self._google_notified = True
                self._start_google("both", speak_errors=False, only_new=True)
                self._google_poll.start()
        self.window.emergency.setToolTip(
            f"The same as {self.controller.settings.emergency_hotkey}. "
            "Turns the AI fully off, even if this window is hidden."
        )

    def _warm_hearing(self) -> None:
        if self.turns.busy():
            return
        if not packages_installed() or not model_ready():
            return
        if getattr(self, "_hearing_job", None) is not None and self._hearing_job.isRunning():
            return

        class _Job(QThread):
            def run(self_job) -> None:
                if self.turns.busy():
                    return
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
        job = _WarmVoiceJob(self.turns.busy)
        self._warm_job = job
        job.start()

    def _on_status(self, snap) -> None:
        self.window.home.set_status(snap)
        self._refresh_game_note()
        self._hide_orb_if_game()
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

    def _set_game_ask(self, enabled: bool) -> None:
        self.controller.set_game_ask(enabled)
        self._refresh_game_note()

    def _offer_game(self, name: str) -> None:
        agreed = ask_yes_no(
            self.window,
            "Switch to game mode?",
            f"{name} is running. Game mode unloads the model so the game can use the graphics card. "
            "The microphone closes. The Game mode button on Home switches immediately, without this question.",
            "Switch",
            "Stay on",
        )
        if agreed:
            self.controller.enter_game()
        else:
            self.controller.games.suppress(name)
            self.controller._remember(
                f"Staying on while {name} is open. The Game mode button still switches."
            )
            self.window.home.set_history(self.controller.history)
        self.controller._game_prompt_open = False

    def _set_detect_games(self, enabled: bool) -> None:
        self.controller.set_detect_games(enabled)
        self._refresh_game_note()

    def _set_journal_enabled(self, enabled: bool) -> None:
        self.controller.set_journal_enabled(enabled)
        note = (
            "The journal is on. It writes program names and minutes, on this PC."
            if enabled
            else "The journal is off. Nothing new is written. The old days stay until you wipe them."
        )
        self.window.home.set_phase(self.controller.state, note)

    def _wipe_journal(self) -> None:
        if not ask_yes_no(
            self.window,
            "Wipe the journal?",
            "This deletes every journal day file from your BabySitter folder. There is no undo.",
            "Wipe it",
            "Keep it",
        ):
            return
        removed = wipe_journal()
        note = f"Wiped the journal. {removed} day files were deleted from this PC."
        self.controller._remember(note)
        self.window.home.set_phase(self.controller.state, note)
        self.window.journal_page.refresh()

    def _add_search_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self.window, "Add a folder to search")
        if not chosen:
            return
        folders = self.controller.settings.search_folders
        if len(folders) >= 20:
            self.window.home.set_phase(
                self.controller.state,
                "Twenty folders is the limit, so this one was not added. Remove one first.",
            )
            return
        if chosen.lower() not in {item.lower() for item in folders}:
            folders.append(chosen)
            save_settings(self.controller.settings)
        self.window.settings_page.search_folders.clear()
        self.window.settings_page.search_folders.addItems(folders)
        self.window.files_page.set_folders(self._search_places())
        self._scan_cache = None

    def _remove_search_folder(self) -> None:
        item = self.window.settings_page.search_folders.currentItem()
        if item is None:
            return
        name = item.text()
        self.controller.settings.search_folders = [
            folder for folder in self.controller.settings.search_folders
            if folder.lower() != name.lower()
        ]
        save_settings(self.controller.settings)
        self.window.settings_page.search_folders.clear()
        self.window.settings_page.search_folders.addItems(self.controller.settings.search_folders)
        self.window.files_page.set_folders(self._search_places())
        self._scan_cache = None

    def _set_core_avoidance(self, enabled: bool) -> None:
        note = self.controller.set_core_avoidance(enabled)
        if note:
            self.window.home.set_phase(self.controller.state, note)

    def _set_flag(self, name: str, enabled: bool) -> None:
        setattr(self.controller.settings, name, bool(enabled))
        save_settings(self.controller.settings)
        self._apply_listen_policy()

    def _apply_listen_policy(self) -> None:
        listener = getattr(self, "_listener", None)
        if listener is None:
            return
        settings = self.controller.settings
        listener.vad_enabled = bool(settings.vad_enabled)
        listener.smart_turn = bool(settings.smart_turn)
        listener.echo_cancel = bool(settings.echo_cancel)
        listener.talk_over = bool(settings.talk_over and settings.echo_cancel)

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
            text = "Auto game mode is off. The Game mode button still switches by hand."
        elif settings.game_mode_ask:
            text = "A game asks before switching. The Game mode button switches immediately."
        elif settings.detect_games and settings.game_processes:
            text = (
                "Watching game folders, and: " + ", ".join(settings.game_processes)
            )
        elif settings.detect_games:
            text = "Watching for any game run from a game folder."
        elif not settings.game_processes:
            text = "Auto game mode is on, but you have not added a program yet."
        else:
            text = "Watching for: " + ", ".join(settings.game_processes)
        self.window.home.game_note.setText(text)

    def _hide_orb_if_game(self) -> None:
        if self._orb_hidden_by_user:
            return
        settings = self.controller.settings
        hide = should_hide_orb(
            settings.hide_orb_for_games,
            foreground_process_name(),
            settings.game_processes,
        )
        if hide:
            self.orb.hide()
        elif not self.orb.isVisible():
            self.orb.show()

    def _save_quiet_hours(self) -> None:
        from babysitter.quiet import parse_hhmm

        page = self.window.settings_page
        try:
            start = parse_hhmm(page.quiet_start.text())
            end = parse_hhmm(page.quiet_end.text())
        except ValueError as exc:
            page.hotkey_note.setText(str(exc))
            return
        self.controller.settings.quiet_start = f"{start.hour:02d}:{start.minute:02d}"
        self.controller.settings.quiet_end = f"{end.hour:02d}:{end.minute:02d}"
        save_settings(self.controller.settings)
        page.hotkey_note.setText("Quiet hours saved on this PC.")

    def _save_searx_port(self) -> None:
        page = self.window.settings_page
        try:
            port = int(page.searx_port.text().strip())
        except ValueError:
            page.hotkey_note.setText("Use a port number, such as 8080.")
            return
        if port < 1 or port > 65535:
            page.hotkey_note.setText("That port is not allowed.")
            return
        self.controller.settings.searx_port = port
        save_settings(self.controller.settings)
        page.hotkey_note.setText("SearXNG port saved. Search still waits for a yes.")

    def _check_updates(self) -> None:
        if not ask_yes_no(
            self.window,
            "Check GitHub for a release?",
            "This asks GitHub if a newer BabySitter release exists. It does not download or install anything.",
            "Check",
            "Don't check",
        ):
            return
        try:
            speech = check_latest()
        except UpdateError as exc:
            speech = str(exc)
        self.window.settings_page.hotkey_note.setText(speech)

    def _download_silero(self) -> None:
        if not ask_yes_no(
            self.window,
            "Download the voice detector?",
            "This saves Silero in your BabySitter folder. It stays off until you turn the detector on in Settings.",
            "Download",
            "Don't download",
        ):
            return
        try:
            speech = download_silero()
        except SileroError as exc:
            speech = str(exc)
        self.window.voice_page.status.setText(speech)

    def _download_embedder(self) -> None:
        from babysitter.embedder import ready as embedder_ready

        running = getattr(self, "_embedder_job", None)
        if running is not None and running.isRunning():
            self.window.home.set_phase(
                self.controller.state, "The sharper memory is already downloading."
            )
            return
        if embedder_ready():
            self.window.memory_page.refresh_sharper()
            return
        if not ask_yes_no(
            self.window,
            "Download the sharper memory?",
            "This downloads a small sentence model (about 90 MB) so saved facts "
            "match by meaning, not just by the same words. It is checked against "
            "a recorded fingerprint, stays in your BabySitter folder, and runs "
            "on the processor. Only the top two matching facts still reach a question.",
            "Download",
            "Don't download",
        ):
            return
        job = _EmbedderDownloadJob()
        self._embedder_job = job
        self.window.home.set_phase(
            self.controller.state, "Downloading the sharper memory onto this PC."
        )
        job.succeeded.connect(self._embedder_downloaded)
        job.failed.connect(self._embedder_download_failed)
        job.start()

    def _embedder_downloaded(self, message: str) -> None:
        self.window.home.set_phase(self.controller.state, message)
        self.window.memory_page.refresh_sharper()
        self.controller._remember(message)

    def _embedder_download_failed(self, message: str) -> None:
        self.window.home.set_phase(self.controller.state, message)
        self.controller._remember(message)

    def _export_session(self) -> None:
        session_id = self.window.history_page.selected_id()
        if not session_id:
            self.window.history_page.body.setPlainText("Choose a conversation first. Nothing was written.")
            return
        try:
            path = export_text(session_id)
        except ValueError as exc:
            self.window.history_page.body.setPlainText(str(exc))
            return
        self.window.history_page.body.append(f"\nExported to {path.name} in the BabySitter folder. It was not uploaded.")

    def _delete_session(self) -> None:
        session_id = self.window.history_page.selected_id()
        if not session_id:
            self.window.history_page.body.setPlainText("Choose a conversation first. Nothing was deleted.")
            return
        if not ask_yes_no(
            self.window,
            "Delete this conversation?",
            "This removes the saved conversation from this PC.",
            "Delete it",
            "Keep it",
        ):
            return
        try:
            delete_session(session_id)
        except ValueError as exc:
            self.window.history_page.body.setPlainText(str(exc))
            return
        self.window.history_page.refresh()

    def _offer_tool(self, intent) -> None:
        if intent.kind == "refuse":
            self.window.home.set_reply("tool", intent.ask, "Nothing was sent.")
            self._speak(intent.ask)
            return
        self._pending_tool = intent
        self.window.home.set_reply(intent.query or "tool", intent.ask, "Nothing is sent until you say yes.")
        self._speak(intent.ask)

    def _answer_tool(self, answer: str) -> None:
        intent = self._pending_tool
        self._pending_tool = None
        if intent is None or answer != "yes":
            self._speak("Leaving it. Nothing was sent.")
            return
        self._tool_summary = intent.summary
        if intent.kind == "web":
            self._run_web(intent)
            return
        self._prepare_search(intent.action_id, intent.query, already_yes=True)

    def _run_web(self, intent) -> None:
        settings = self.controller.settings
        if not settings.searx_enabled:
            self._tool_summary = ""
            self._speak("Web search is off. Turn on SearXNG in Settings. Nothing was sent.")
            return
        try:
            detail = searx_search(settings.searx_port, intent.query)
        except SearxError as exc:
            self._tool_summary = ""
            self._speak(str(exc))
            return
        self.window.tools_page.show_message(detail)
        summary = self._tool_summary
        self._tool_summary = ""
        if summary and self.controller.state == "on":
            self._pending_line = guarded_prompt(summary, detail[:2000])
            self._send_heard()
            return
        self._speak("The results are on the Tools tab.")

    def _fill_settings(self) -> None:
        page = self.window.settings_page
        toggles = page.toggles()
        for toggle in toggles:
            toggle.blockSignals(True)
        page.fill(self.controller.settings, self.controller.data_folder())
        for toggle in toggles:
            toggle.blockSignals(False)
        journal = self.window.journal_page
        journal.enabled.blockSignals(True)
        journal.enabled.setChecked(self.controller.settings.journal_enabled)
        journal.enabled.blockSignals(False)
        self.window.files_page.set_folders(self._search_places())

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
        word = STATE_WORDS.get(state, "Needs you")
        latest = self.controller.history[-1] if self.controller.history else ""
        header = menu.addAction(f"{word} — {latest[:60]}" if latest else word)
        header.setEnabled(False)
        menu.addSeparator()
        if state in {"on", "game"} or self.controller._busy:
            menu.addAction("Turn the AI off", lambda: self.controller.turn_off())
        else:
            menu.addAction("Turn the AI on", self._turn_on)
        if state == "game":
            menu.addAction("Wake up (leave game mode)", self.controller.wake)
        elif state == "on":
            menu.addAction("Game mode", self.controller.enter_game)
        menu.addAction(
            f"Emergency stop ({self.controller.settings.emergency_hotkey})",
            lambda: self.controller.turn_off(emergency=True),
        )
        menu.addSeparator()
        menu.addAction("Open BabySitter", self.show_window)
        top = menu.addAction("Always on top")
        top.setCheckable(True)
        top.setChecked(self.controller.settings.orb_always_on_top)
        top.triggered.connect(self._menu_on_top)
        if self._orb_hidden_by_user:
            menu.addAction("Show the orb", lambda: self._set_orb_hidden(False))
        else:
            menu.addAction("Hide the orb", lambda: self._set_orb_hidden(True))
        menu.addSeparator()
        menu.addAction("Quit…", self._quit)

    def _set_orb_hidden(self, hidden: bool) -> None:
        self._orb_hidden_by_user = bool(hidden)
        self.orb.setVisible(not hidden)

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

    def _save_window_mode(self, expanded: bool) -> None:
        self.controller.settings.window_expanded = bool(expanded)
        save_settings(self.controller.settings)

    def _set_quit_off(self, on: bool) -> None:
        self.controller.settings.quit_turns_ai_off = bool(on)
        save_settings(self.controller.settings)

    def _ptt_tick(self) -> None:
        """Mouse side buttons. Polling does not swallow the click."""
        allowed = (
            sys.platform == "win32"
            and self.controller.settings.side_button
            and self.controller.state == "on"
        )
        if not allowed:
            if getattr(self, "_holding", False) and getattr(self, "_hold_from_mouse", False):
                self._hold_from_mouse = False
                self._hold_up()
            return
        from babysitter.sidebutton import SIDE_BUTTONS

        down = any(
            bool(ctypes.windll.user32.GetAsyncKeyState(button) & 0x8000) for button in SIDE_BUTTONS
        )
        if not down:
            self._ptt_latched = False
            if getattr(self, "_holding", False) and getattr(self, "_hold_from_mouse", False):
                self._hold_from_mouse = False
                self._hold_up()
            return
        if getattr(self, "_ptt_latched", False) or getattr(self, "_holding", False):
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
        self._release_speech()
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
        self._show_mode("listening", "Listening. Release to stop.")
        if packages_installed() and model_ready():
            try:
                self._recorder.start()
                self._recording = True
                self.window.home.set_phase("listening", "The microphone is open only while you hold.")
            except HearingError as exc:
                self._holding = False
                self._recorder.close()
                self.window.home.set_reply("nothing", "The microphone did not open.", str(exc))
                self._show_mode(self.controller.state, "Hold to talk")
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
            self._show_mode(self.controller.state, "Hold to talk")
            self.window.home.set_phase(self.controller.state, "The microphone stays closed until you hold to talk.")
            self._pending_line = ""
            self.window.home.set_reply(
                "(no words yet)",
                "I didn't hear words.",
                "Open the Voice tab and click Download speech recognition. Nothing was sent.",
            )
            self._sync_keyword()
            return
        self._show_mode("thinking", "Turning speech into text on this PC.")
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
            self._show_mode(self.controller.state, "Say the keyword")
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
        if self._pending_tool is not None:
            answer = suggestion_answer(text)
            if answer:
                self._answer_tool(answer)
                return
            self._pending_tool = None
        if self._suggestions and self._suggestion_at < len(self._suggestions):
            answer = suggestion_answer(text)
            if answer:
                self._answer_suggestion(answer)
                return
            self._suggestions = []
            self._arm_yes_no(bool(getattr(self, "_awaiting_more", False)))
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
                current = str(self._history[-1].get("content") or "")
                if rest and rest not in current:
                    self._history[-1]["content"] = (current + " " + rest).strip()
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
        if match_quick_command(text) is None:
            self.window.home.set_reply(text, "Sending it to the model on this PC.", "")
        self._send_heard()

    def _hear_failed(self, message: str) -> None:
        self.window.home.set_reply("(no words yet)", "I didn't hear words.", message)
        self._show_mode(self.controller.state, "Say the keyword")
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
        self._apply_listen_policy()
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
        if status == "talk_over":
            self._cut_off()
            self.window.home.set_phase("on", "Stopped. I heard you over the voice.")
            return
        if status == "capturing":
            self._show_mode("listening", "Listening to the question.")
            self.window.home.set_phase("listening", "Say the question now. The microphone is open.")
            return
        if getattr(self, "_followup_left", 0) > 0:
            self._show_followup()
            return
        if getattr(self, "_awaiting_more", False):
            self._show_mode("on", "Say yes or no")
            self.window.home.set_phase(
                "on",
                "Say yes to hear the rest, or no to stop there. "
                f"A new question still starts with {word}.",
            )
            return
        self._show_mode("on", f"Say {word}")
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
        typed_quick = match_quick_command(text)
        if typed_quick is not None and typed_quick.kind == "undo":
            self.window.home.typed.clear()
            self._undo_timer()
            return
        if self._pending_tool is not None:
            answer = suggestion_answer(text)
            if answer:
                self.window.home.typed.clear()
                self._answer_tool(answer)
                return
            self._pending_tool = None
        if self._suggestions and self._suggestion_at < len(self._suggestions):
            answer = suggestion_answer(text)
            if answer:
                self.window.home.typed.clear()
                self._answer_suggestion(answer)
                return
            self._suggestions = []
            self._arm_yes_no(bool(getattr(self, "_awaiting_more", False)))
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
        if typed_quick is not None:
            self._send_heard()
            return
        self.window.home.set_reply(text, "Waiting.", "Nothing has been sent yet.")

    def _send_heard(self) -> None:
        text = getattr(self, "_pending_line", "").strip()
        if not text:
            self.window.home.set_reply("nothing", "Type a line first.", "Nothing was sent.")
            return
        if self._run_quick(text):
            return
        self._scan_when_free = False
        if self.controller.state == "game":
            self._offer_load = True
            self._close_followup()
            mode = get_mode(self.controller.settings.intelligence)
            gigabytes = max(1, round(mode.vram_mib / 1024))
            self._speak(f"I'm in Game mode. Load the brain? It needs about {gigabytes} GB of video memory.")
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
        self._filler_stop.clear()
        self._filler.start(1500)
        self._begin_model_turn()
        note = getattr(self, "_interrupt_note", "")
        if note:
            text = f"{note}\n{text}"
            self._interrupt_note = ""
        alive = "2m" if getattr(self, "_return_to_game", False) else IDLE_KEEP_ALIVE
        facts = self._facts_for(text)
        job = _AskJob(
            self.controller.ollama,
            mode.model,
            text,
            mode.num_ctx,
            self._history,
            keep_alive=alive,
            num_batch=mode.num_batch,
            facts=facts,
            personality=getattr(self, "_session_personality", ""),
        )
        job.turn = self._turn_id
        self._ask_job = job
        job.measured.connect(lambda stats, turn=job.turn: self._on_measured(stats, turn))
        job.first_token.connect(lambda turn=job.turn: self._on_first_token(turn))
        job.lead_ready.connect(lambda lead, turn=job.turn: self._lead_ready(lead, turn))
        job.succeeded.connect(lambda reply, turn=job.turn: self._asked(reply, turn))
        job.failed.connect(lambda message, heard=text, turn=job.turn: self._ask_failed(heard, message, turn))
        self._show_mode("thinking", "Thinking.")
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

    def _facts_for(self, text: str) -> list[str]:
        items = [str(item.get("text") or "") for item in load_list("memory.json")]
        return rank_texts(text, items, k=2)

    def _begin_model_turn(self) -> None:
        if self._model_turn_open:
            return
        self.turns.enter()
        self._model_turn_open = True
        self.controller.probe.defer_probes = True

    def _end_model_turn(self) -> None:
        if not self._model_turn_open:
            return
        self.turns.leave()
        self._model_turn_open = False
        self.controller.probe.defer_probes = False

    def _cue_waiting(self) -> None:
        clock = getattr(self, "_clock", None)
        if clock is None or "first_sound" in clock.marks or not self._same_turn(self._turn_id):
            return
        from babysitter.plugins.voice.fillers import PHRASES, library

        index = self._filler_n % len(PHRASES)
        line = PHRASES[index]
        self._filler_n += 1
        self.window.home.set_phase("thinking", line)
        self._show_mode("thinking", line)
        clip = library().clip(index)
        if clip is None or getattr(self, "_speaking", False):
            return
        pcm, rate = clip
        self._filler_stop.clear()
        self._speaking = True
        self._is_filler = True

        class _Play(QThread):
            def run(self_play) -> None:
                from babysitter.plugins.voice.fillers import play_clip

                play_clip(pcm, rate, self._filler_stop)

        job = _Play()
        self._filler_job = job
        job.finished.connect(self._filler_done)
        job.start()
        if clock is not None:
            clock.mark("first_sound")
            self._responsiveness.add(clock.as_row())
            self.window.voice_page.set_responsiveness(self._responsiveness.summary())

    def _filler_done(self) -> None:
        if getattr(self, "_is_filler", False):
            self._is_filler = False
            self._speaking = False
            self._sync_keyword()
            self._release_waiting_scan()

    def _cut_off(self) -> None:
        started = time.perf_counter()
        self._turn_id += 1
        self._filler.stop()
        self._filler_stop.set()
        self._end_model_turn()
        job = getattr(self, "_ask_job", None)
        if job is not None:
            job.cancel.set()
        self._release_speech()
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
        self._filler_stop.set()
        self._release_speech()
        self._end_model_turn()
        self._pending_offer = ""
        self.window.home.set_reply(heard, "The model did not answer.", message)
        self._speaking = False
        self._sync_keyword()
        self._release_waiting_scan()

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
        self._speak(lead, hold_open=True)

    def _asked(self, reply: str, turn: int = 0) -> None:
        if turn and not self._same_turn(turn):
            return
        early = getattr(self, "_early_lead", "")
        spoken, rest = voice_and_rest(reply)
        spoken = spoken or early or "I don't have an answer for that."
        self._last_reply = (spoken[:80] or "Reply", reply)
        self._full_reply = reply
        self._spoken_for_history = remembered_reply(reply) or spoken
        heard = getattr(self, "_pending_line", "")
        self._remember_exchange(heard, self._spoken_for_history)
        self._more_text = rest
        level = int(self.controller.settings.proactivity)
        fact = ""
        if level >= 2:
            matches = self._facts_for(heard)
            fact = matches[0] if matches else ""
        from datetime import date as _date

        weekly = False
        if level >= 3 and not self._weekly_offered:
            from babysitter.proactivity import offer_weekly

            weekly = offer_weekly(
                level,
                self.controller.settings.last_weekly_review,
                _date.today(),
                self._weekly_offered,
            )
            if weekly:
                self._weekly_offered = True
        self._awaiting_more = offer_more(level, bool(rest))
        if self._awaiting_more and getattr(self, "_listener", None) is not None:
            self._listener.expect_yes_no(True)
        note = nudge(level, bool(rest), fact, weekly)
        self._nudge = note
        detail = unread_detail(spoken, reply)
        if note:
            detail = f"{detail}\n\n{note}".strip() if detail else note
        self.window.home.set_reply(heard, spoken, detail)
        if early:
            extra = rest_after_lead(early, spoken)
            self._early_lead = ""
            job = getattr(self, "_speak_job", None)
            if job is not None and job.isRunning():
                if extra:
                    job.add(extra)
                job.close_input()
                return
            if extra:
                self._speak(extra)
                return
            self._end_model_turn()
            self._release_waiting_scan()
            return
        self._speak(spoken)
        if not getattr(self, "_speaking", False):
            self._end_model_turn()
            self._release_waiting_scan()

    def _clear_more(self) -> None:
        self._awaiting_more = False
        self._more_text = ""
        if getattr(self, "_listener", None) is not None:
            self._listener.expect_yes_no(False)

    def _decline_more(self) -> None:
        self._clear_more()
        self.window.home.set_phase("on", "Okay. I'll stop there.")
        self._show_mode(self.controller.state, "Say the keyword")
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

    def _release_speech(self) -> None:
        job = getattr(self, "_speak_job", None)
        if job is not None:
            job.close_input()

    def _pin_line(self, text: str) -> None:
        line = " ".join((text or "").split())
        if not line:
            return
        self._pin_note(line[:80], line)

    def _pin_note(self, title: str, body: str) -> None:
        title = " ".join((title or "").split())[:80]
        body = " ".join((body or "").split())[:2000]
        if not title and not body:
            return
        if len(load_list("pins.json")) >= 12:
            self.window.home.set_reply(
                "pin", "The board is full.", "Twelve cards is the limit. Unpin one first."
            )
            return
        add_item("pins.json", title=title or body[:80], body=body or title)
        self._refresh_pins()
        self.controller._remember("Pinned a note. It stays on this PC.")
        self.window.home.set_history(self.controller.history)

    def _pin_reply(self) -> None:
        last = getattr(self, "_last_reply", None)
        if not last:
            self.window.home.set_reply("nothing", "Nothing to pin yet.", "Send a reply first, or save a reminder.")
            return
        if len(load_list("pins.json")) >= 12:
            self.window.home.set_reply(
                "pin", "The board is full.", "Twelve cards is the limit. Unpin one first."
            )
            return
        title, body = last
        add_item("pins.json", title=title, body=body)
        self._refresh_pins()
        self.window.home.set_reply(title, "Pinned.", "The card stays on this PC.")

    def _copy_reply(self) -> None:
        spoken = self.window.home.spoken.text().strip()
        detail = self.window.home.reply_detail.text().strip()
        text = "\n\n".join(part for part in (spoken, detail) if part)
        QApplication.clipboard().setText(text)
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
        if text == "JOURNAL today":
            self._speak_journal("what did i do today", False)
            return
        if text == "JOURNAL yesterday":
            self._speak_journal("what did i do yesterday", True)
            return
        if text in {"JOURNAL pause", "JOURNAL resume"}:
            paused = text.endswith("pause")
            speech = self.controller.set_journal_paused(paused)
            self.window.home.set_reply(text.split()[1], speech, "The journal lives in your BabySitter folder.")
            self._speak(speech)
            return
        if text.startswith("TASK start "):
            self._journal_task("start task", start=text[len("TASK start "):].strip())
            return
        if text == "TASK done":
            self._journal_task("done")
            return
        if text == "WIPE journal":
            self._wipe_journal()
            return
        if text.startswith("FIND "):
            wanted = text[len("FIND "):].strip()
            self._find_files(f"find {wanted}", wanted)
            return
        if text.startswith("CONFIRM reminder:"):
            from babysitter.commands import reminder_fields

            raw = text.split(":", 1)[1]
            when = ""
            if "\nWHEN:" in raw:
                raw, when = raw.split("\nWHEN:", 1)
            detail, due = reminder_fields(raw.strip(), when.strip(), datetime.now().astimezone())
            self.window.schedule_page.text.clear()
            self.window.schedule_page.when.clear()
            self._save_local("schedule.json", detail, "the reminder", due=due)
            return
        if text.startswith("CONFIRM memory:"):
            body = text.split(":", 1)[1].strip()
            self.window.memory_page.text.clear()
            self._save_local("memory.json", body, "that")
            return
        if text == "SCAN pc":
            self._begin_scan()
            return
        if text == "INSTALL silero":
            self._download_silero()
            return
        if text == "INSTALL embedder":
            self._download_embedder()
            return
        if text == "EXPORT session":
            self._export_session()
            return
        if text == "DELETE session":
            self._delete_session()
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
        if text.startswith("PROACTIVITY "):
            self._save_proactivity(text)
            return
        if text.startswith("RATE "):
            self._save_rating(text.split(" ", 1)[1])
            return
        if text == "WEEKLY review":
            self._speak_weekly()
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
        mode = get_mode(self.controller.settings.intelligence)
        native = full and mode.num_ctx > 4096
        edge = mode.image_edge if not full else 1280
        screen = QApplication.primaryScreen()
        if screen is None:
            self.window.screen_page.body.setPlainText("No screen was found. Nothing was saved.")
            return
        picture = screen.grabWindow(0)
        if native:
            self.window.home.set_phase("thinking", "This takes a few seconds.")
        else:
            width, height = fit_screenshot(picture.width(), picture.height(), edge=edge, num_ctx=mode.num_ctx)
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
        alive = "2m" if getattr(self, "_return_to_game", False) else IDLE_KEEP_ALIVE
        self._begin_model_turn()
        job = _AskJob(
            self.controller.ollama,
            mode.model,
            text,
            mode.num_ctx,
            self._history,
            [encoded],
            keep_alive=alive,
            num_batch=mode.num_batch,
            facts=self._facts_for(text),
            personality=getattr(self, "_session_personality", ""),
        )
        job.turn = self._turn_id
        self._ask_job = job
        job.measured.connect(lambda stats, turn=job.turn: self._on_measured(stats, turn))
        job.first_token.connect(lambda turn=job.turn: self._on_first_token(turn))
        job.lead_ready.connect(lambda lead, turn=job.turn: self._lead_ready(lead, turn))
        job.succeeded.connect(lambda reply, turn=job.turn: self._asked(reply, turn))
        job.failed.connect(lambda message, heard=text, turn=job.turn: self._ask_failed(heard, message, turn))
        self._show_mode("thinking", "Looking.")
        job.start()

    def _read_health(self) -> None:
        if self.turns.busy():
            self.window.health_page.body.setPlainText("A reply is in progress. The PC check waits until it finishes.")
            return
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

    def _speak(self, text: str, filler: bool = False, hold_open: bool = False, alert: bool = False) -> None:
        self._is_filler = filler
        self._alert_speech = bool(alert)
        previous = getattr(self, "_speak_job", None)
        if previous is not None:
            previous.close_input()
        stop_kokoro()
        speaker.stop()
        self._speaking = True
        self._pending_speech = text
        allow_barge = self.controller.settings.talk_over and self.controller.settings.echo_cancel
        if getattr(self, "_listener", None) is not None and not allow_barge:
            self._listener.stop()
        prefs = self._voice_prefs()
        if alert and (prefs.get("engine") != "kokoro" or not kokoro_ready()):
            from babysitter.plugins.voice.windows_voice import available as windows_voice_available

            prefs = alert_voice(prefs, kokoro_ready=kokoro_ready(), windows_ok=windows_voice_available())
            if prefs is None:
                self._alert_speech = False
                self._speaking = False
                self.window.home.set_phase(
                    self.controller.state,
                    "The reminder is in the notification. No voice is loaded, and the AI stays off.",
                )
                return
        elif filler and prefs["engine"] == "kokoro" and not kokoro_ready():
            self._is_filler = False
            self._speaking = False
            return
        elif prefs["engine"] == "kokoro" and not kokoro_ready():
            self._offer_kokoro()
            return
        if prefs["engine"] == "windows" and sys.platform != "win32":
            self._speaking = False
            if alert:
                self._alert_speech = False
                self.window.home.set_phase(
                    self.controller.state,
                    "The reminder is in the notification. The Windows voice is not on this PC, and the AI stays off.",
                )
                return
            if not filler:
                self._end_model_turn()
                self._release_waiting_scan()
            self._sync_keyword()
            return
        self._start_speech(text, prefs, hold_open=hold_open)

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
            self._end_model_turn()
            self._release_waiting_scan()
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
        self._end_model_turn()
        self.window.home.set_phase("on", message)
        self._sync_keyword()
        self._release_waiting_scan()

    def _start_speech(self, text: str, prefs: dict, hold_open: bool = False) -> None:
        if not text:
            self._speaking = False
            if not getattr(self, "_is_filler", False):
                self._end_model_turn()
                self._release_waiting_scan()
            self._sync_keyword()
            return
        job = _SpeakJob(text, prefs, self._turn_id)
        self._speak_job = job
        self._show_mode("speaking", text)
        self.window.home.set_phase("speaking", f"Speaking with {prefs['label']}.")
        job.started.connect(self._sound_started)
        job.phrase_done.connect(self._phrase_finished)
        job.failed.connect(self._speech_failed)
        job.finished.connect(self._speak_done)
        job.start()
        if not hold_open:
            job.close_input()

    def _sound_started(self) -> None:
        self._filler.stop()
        self._filler_stop.set()
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
        self._end_model_turn()
        self.window.home.set_phase(self.controller.state, message)

    def _speak_done(self) -> None:
        self._speaking = False
        if getattr(self, "_alert_speech", False):
            self._alert_speech = False
            self._show_mode(self.controller.state, "Reminder said.")
            self.window.home.set_phase(self.controller.state, "Reminder said. The AI was not turned on.")
            self._sync_keyword()
            return
        if getattr(self, "_is_filler", False):
            self._is_filler = False
            self._release_waiting_scan()
            return
        if getattr(self, "_pending_offer", ""):
            offer = self._pending_offer
            self._pending_offer = ""
            self._speak(offer)
            return
        self._remember_exchange(getattr(self, "_pending_line", ""), getattr(self, "_spoken_for_history", ""))
        job = getattr(self, "_ask_job", None)
        if job is None or not job.isRunning():
            self._end_model_turn()
        self._arm_game_return()
        nudge_line = getattr(self, "_nudge", "")
        if nudge_line:
            self.window.home.set_phase("on", nudge_line)
            self._nudge = ""
        if self._release_waiting_scan():
            return
        self._open_followup()

    def _note_local(self, user: str, assistant: str) -> None:
        """Keep a local answer in the conversation, so the next question still knows it.

        If the model was still speaking, its answer is kept first. Otherwise the
        clock or the reminder would replace it.
        """
        if not getattr(self, "_logged_turn", False):
            pending = getattr(self, "_pending_line", "")
            spoken = getattr(self, "_spoken_for_history", "") or " ".join(getattr(self, "_finished_phrases", []))
            if (pending or spoken) and pending != user:
                self._remember_exchange(pending, spoken)
        self._logged_turn = False
        self._remember_exchange(user, assistant)

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
        try:
            if not self._session_id:
                self._session_id = begin_session()
            append_turn(self._session_id, user, assistant)
            self.window.history_page.refresh()
        except ValueError:
            return

    def _open_followup(self) -> None:
        settings = self.controller.settings
        listening = settings.keyword_listening and self.controller.state == "on"
        ready = keyword_packages_installed() and keyword_model_ready()
        if not listening or not ready or getattr(self, "_listener", None) is None:
            self._show_mode(self.controller.state, "Say the keyword")
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
        self._show_mode("on", f"Follow-up {left}")
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
        self._show_mode(self.controller.state, "Say the keyword")
        self._sync_keyword()

    def _run_quick(self, text: str) -> bool:
        quick = match_quick_command(text)
        if quick is not None and quick.kind == "undo":
            return False
        if quick is None:
            intent = match_tool(text)
            if intent is None:
                return False
            self._offer_tool(intent)
            return True
        if quick.kind == "time":
            now = datetime.now().astimezone()
            speech = now.strftime("It's %A, %B %d, %I:%M %p.").replace(" 0", " ")
            self.window.home.set_reply(text, speech, "Read from this PC. The model was not asked.")
            self._note_local(text, speech)
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
            self._note_local(text, speech)
            self._speak(speech)
            return True
        if quick.kind == "health":
            snap = getattr(self.controller, "latest_status", None)
            if snap is None:
                speech = spoken_reading(0, 0, None)
            else:
                speech = spoken_reading(snap.ram_used_bytes, snap.ram_total_bytes, snap.cpu_percent)
            self.window.home.set_reply(text, speech, "Read from this PC. Nothing was changed.")
            self._note_local(text, speech)
            self._speak(speech)
            return True
        if quick.kind == "screen":
            self._look_at_screen()
            return True
        if quick.kind == "screen_text":
            self._look_at_screen(full=True)
            return True
        if quick.kind == "why":
            query = text
            for item in reversed(self._history):
                if item.get("role") == "user":
                    query = str(item.get("content") or query)
                    break
            facts = self._facts_for(query)
            lines = []
            for item in self._history[-6:]:
                role = "You" if item.get("role") == "user" else "BabySitter"
                lines.append(f"{role}: {str(item.get('content') or '')[:240]}")
            if facts:
                lines.append("Saved facts that matched:")
                lines.extend(facts)
                speech = "I used the recent conversation and the saved facts that matched. Both are on the screen."
            else:
                speech = "I used the recent conversation. No saved fact matched. It is on the screen."
            detail = "\n".join(lines) if lines else "Nothing from this conversation was kept."
            self.window.home.set_reply(text, speech, detail)
            self._note_local(text, speech)
            self._speak(speech)
            return True
        if quick.kind == "weekly":
            self._speak_weekly()
            return True
        if quick.kind == "rate":
            self._save_rating(quick.detail)
            return True
        if quick.kind == "timer":
            self._begin_timer(quick.seconds, quick.detail)
            return True
        if quick.kind == "scan":
            self._begin_scan()
            return True
        if quick.kind == "mail":
            self._start_google("mail", speak_errors=True)
            return True
        if quick.kind == "calendar":
            self._start_google("calendar", speak_errors=True)
            return True
        if quick.kind == "history":
            self._speak_saved_history(text)
            return True
        if quick.kind in {"remember", "remind"}:
            filename = "memory.json" if quick.kind == "remember" else "schedule.json"
            noun = "that" if quick.kind == "remember" else "the reminder"
            shown = text.strip()
            if quick.kind == "remind" and quick.when:
                moment = datetime.fromisoformat(quick.when)
                shown = f"{spoken_clock(moment)} — {quick.detail}".strip(" —")
            self._save_local(filename, shown, noun, due=quick.when)
            return True
        if quick.kind in {"journal_today", "journal_yesterday"}:
            self._speak_journal(text, quick.kind == "journal_yesterday")
            return True
        if quick.kind == "task_start":
            self._journal_task(text, start=quick.detail)
            return True
        if quick.kind == "task_done":
            self._journal_task(text)
            return True
        if quick.kind in {"journal_pause", "journal_resume"}:
            speech = self.controller.set_journal_paused(quick.kind == "journal_pause")
            self.window.journal_page.set_paused(quick.kind == "journal_pause")
            self.window.home.set_reply(text, speech, "The journal lives in your BabySitter folder.")
            self._speak(speech)
            return True
        if quick.kind == "find":
            self._find_files(text, quick.detail)
            return True
        if quick.kind == "open_number":
            self._open_numbered(text, quick.seconds)
            return True
        return False

    def _speak_journal(self, text: str, yesterday: bool) -> None:
        day = date.today() - timedelta(days=1) if yesterday else date.today()
        record = load_day(day)
        word = "yesterday" if yesterday else "today"
        speech = day_speech(record, word)
        self.window.home.set_reply(text, speech, day_detail(record))
        if not yesterday:
            self.window.journal_page.refresh()
        self._note_local(text, speech)
        self._speak(speech)

    def _journal_task(self, text: str, start: str = "") -> None:
        moment = datetime.now()
        record = load_day(moment.date())
        if start:
            speech = start_task(record, start, moment)
        else:
            speech = finish_task(record, moment)
            if speech.startswith("No task is open"):
                # A task started before midnight is finished on yesterday's page.
                yesterday = load_day(moment.date() - timedelta(days=1))
                closed = finish_task(yesterday, moment, quiet=True)
                if closed:
                    record = yesterday
                    speech = closed
        try:
            save_day(record)
        except OSError:
            speech = "The journal file could not be written, so that was not kept."
        self.window.home.set_reply(text, speech, "Tasks live in the journal, in your BabySitter folder.")
        self.window.journal_page.refresh()
        self._note_local(text, speech)
        self._speak(speech)

    def _search_places(self) -> list[str]:
        return default_folders() + list(self.controller.settings.search_folders)

    def _find_files(self, text: str, wanted: str) -> None:
        now = time.time()
        cached = getattr(self, "_scan_cache", None)
        if cached and now - cached[0] < CACHE_SECONDS:
            self._finish_find(text, wanted, cached[1], recently_opened())
            return
        running = getattr(self, "_find_job", None)
        if running is not None and running.isRunning():
            speech = "Still looking through the folders. Ask again in a moment."
            self.window.home.set_reply(text, speech, "One search runs at a time.")
            self._speak(speech)
            return
        job = _FindJob(self._search_places())
        self._find_job = job
        self.window.home.set_phase(self.controller.state, "Looking through your folders…")
        self.window.files_page.set_busy_line("Looking through your folders…")
        job.finished_scan.connect(lambda payload: self._scan_arrived(text, wanted, payload))
        job.start()

    def _scan_arrived(self, text: str, wanted: str, payload: object) -> None:
        entries, opened = payload
        self._scan_cache = (time.time(), entries)
        self._finish_find(text, wanted, entries, opened)

    def _finish_find(self, text: str, wanted: str, entries, opened) -> None:
        matches = match_files(wanted, entries, opened)
        speech, detail, best = search_reply(wanted, matches, self._search_places())
        self._found_files = matches
        self._found_at = time.time()
        if best is not None:
            outcome = open_found(best)
            if not outcome.startswith("Opened"):
                speech = outcome
        self.window.home.set_reply(text, speech, detail)
        self.window.files_page.set_results(speech, detail)
        self._speak(speech)

    def _open_numbered(self, text: str, number: int) -> None:
        matches = getattr(self, "_found_files", None) or []
        if not matches:
            speech = "Nothing is on the list. Say find and a file name first."
            self.window.home.set_reply(text, speech, "The search looks only in your chosen folders.")
            self._speak(speech)
            return
        if time.time() - getattr(self, "_found_at", 0.0) > 600:
            self._found_files = []
            speech = "That list is from a while ago, so nothing was opened. Say find again for a fresh one."
            self.window.home.set_reply(text, speech, "A numbered list is good for 10 minutes.")
            self._speak(speech)
            return
        if number < 1 or number > len(matches):
            speech = f"The list goes from 1 to {len(matches)}."
            self.window.home.set_reply(text, speech, "Say open number and one of those.")
            self._speak(speech)
            return
        found = matches[number - 1]
        speech = open_found(found)
        self.window.home.set_reply(text, speech, found.path)
        self._speak(speech)

    def _begin_timer(self, seconds: int, detail: str = "") -> None:
        """A spoken timer is a reminder due that many seconds from now."""
        previous = getattr(self, "_active_timer", None)
        if previous is not None:
            previous.stop()
        moment = datetime.now().astimezone() + timedelta(seconds=seconds)
        text = " ".join((detail or "Timer").split())[:200] or "Timer"
        item = self._save_local("schedule.json", text, "the reminder", due=moment.isoformat(timespec="seconds"))
        if not item:
            return
        label = timer_label(seconds)
        timer = QTimer(self.window)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda item_id=item["id"], name=text: self._timer_finished(name, item_id))
        timer.start(seconds * 1000)
        self._active_timer = timer
        self._active_timer_id = item["id"]
        self.window.home.set_reply(
            "timer",
            self.window.home.spoken.text(),
            f"It is a reminder for {label}. It stays on this PC and rings while BabySitter is open.",
        )

    def _undo_timer(self) -> None:
        now = time.time()
        if now <= getattr(self, "_undo_until", 0) and getattr(self, "_active_timer", None) is not None:
            self._active_timer.stop()
            self._active_timer = None
            self._undo_until = 0
            self.window.home.set_reply("undo", "Cancelled the timer.", "Nothing else was changed.")
            self._speak("Cancelled the timer.")
            return
        soft = getattr(self, "_soft_undo", None)
        if soft and now <= float(soft.get("until") or 0):
            self._undo_soft(soft)
            return
        self._speak("Nothing to undo.")

    def _undo_soft(self, soft: dict) -> None:
        self._soft_undo = None
        kind = soft.get("kind")
        if kind == "note":
            timer = getattr(self, "_active_timer", None)
            if timer is not None and str(soft.get("id") or "") == str(getattr(self, "_active_timer_id", "")):
                timer.stop()
                self._active_timer = None
            remove_item(str(soft.get("file") or ""), str(soft.get("id") or ""))
            self.window.schedule_page.refresh()
            self.window.memory_page.refresh()
            speech = "Removed that."
        elif kind == "close":
            speech = "I can't reopen it. It is already closed."
        elif kind == "startup":
            try:
                self._startup_store.restore(str(soft.get("name") or ""), str(soft.get("command") or ""))
                speech = "Turned it back on at startup."
            except Exception:
                speech = "I could not put that startup item back."
        else:
            speech = "Nothing to undo."
        self.window.home.set_reply("undo", speech, "Nothing else was changed.")
        self._speak(speech)

    def _save_local(self, filename: str, text: str, noun: str, due: str = "") -> None:
        fields = {"text": text}
        if due:
            fields["due"] = due
        item = add_item(filename, **fields)
        self._soft_undo = {
            "kind": "note",
            "until": time.time() + 10,
            "file": filename,
            "id": item["id"],
        }
        if filename.startswith("schedule"):
            self.window.schedule_page.refresh()
        else:
            self.window.memory_page.refresh()
        if due:
            moment = datetime.fromisoformat(due)
            speech = (
                f"Reminder set for {spoken_clock(moment)}. "
                "I'll say it then, and show a notification on this PC, even if the AI is off. "
                "Say undo in the next 10 seconds to remove it."
            )
        else:
            speech = f"Saved {noun}. Say undo in the next 10 seconds to remove it."
            if filename.startswith("schedule"):
                speech = (
                    "Saved the reminder. It has no clock, so it will not ring. "
                    "Add a time on the Reminders page. Say undo in the next 10 seconds to remove it."
                )
        self.window.home.set_reply(text[:80], speech, "It stays on this PC. Nothing was sent.")
        self._note_local(text, speech)
        self._speak(speech)
        return item

    def _check_reminders(self) -> None:
        """Say a saved reminder once its clock time has arrived."""
        if getattr(self, "_speaking", False):
            return
        now = datetime.now().astimezone()
        items = load_list("schedule.json")
        pending = None
        for item in items:
            due = str(item.get("due") or "")
            if not due or str(item.get("fired") or "") == "yes":
                continue
            try:
                moment = datetime.fromisoformat(due)
            except ValueError:
                continue
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=now.tzinfo)
            if moment <= now:
                pending = item
                break
        if pending is None:
            return
        pending["fired"] = "yes"
        save_list("schedule.json", items)
        self.window.schedule_page.refresh()
        words = str(pending.get("text") or "Reminder.")
        speech = f"Reminder. {words}"
        self.window.home.set_reply(
            "reminder",
            speech,
            "Said on this PC while BabySitter is open. The AI can be off. Nothing was sent.",
        )
        self.tray.notify("Reminder", speech)
        self._speak(speech, alert=True)

    def _speak_saved_history(self, text: str) -> None:
        """Read the saved conversation here. The model is not asked, and the voice gets a short piece."""
        from babysitter.plugins.voice.speech import first_sentence
        from babysitter.sessions import list_sessions, load_session

        rows = list_sessions()
        if not rows:
            speech = "There isn't a saved conversation yet."
            self.window.home.set_reply(text, speech, "Conversations are saved on this PC after a reply finishes.")
            self._speak(speech)
            return
        try:
            record = load_session(str(rows[0].get("id") or ""))
        except ValueError:
            speech = "The saved conversation could not be read."
            self.window.home.set_reply(text, speech, "It stays in your BabySitter folder.")
            self._speak(speech)
            return
        turns = [turn for turn in record.get("turns") or [] if isinstance(turn, dict)]
        recent = turns[-4:]
        lines: list[str] = []
        for turn in recent:
            you = " ".join(str(turn.get("user") or "").split())
            mine = first_sentence(str(turn.get("assistant") or ""))
            if you:
                lines.append(f"You said: {you[:160]}.")
            if mine:
                lines.append(f"I said: {mine[:160]}")
        if not lines:
            speech = "That conversation has no lines yet."
        elif len(recent) < len(turns):
            speech = "Here are the last few lines. " + " ".join(lines)
        else:
            speech = " ".join(lines)
        detail = "\n".join(lines) if lines else "Nothing was read."
        self.window.home.set_reply(text, speech, detail)
        self._speak(speech)

    def _model_still_running(self) -> bool:
        job = getattr(self, "_ask_job", None)
        return job is not None and job.isRunning() and not job.cancel.is_set()

    def _scan_blocked(self) -> bool:
        if getattr(self, "_speaking", False):
            return True
        if self._model_still_running():
            return True
        return bool(self.turns.busy())

    def _defer_scan(self) -> None:
        """Hold the scan until the reply in progress has finished speaking."""
        self._scan_when_free = True
        self.window.home.set_phase(self.controller.state, "I'll scan as soon as this reply finishes.")
        job = getattr(self, "_ask_job", None)
        finished = getattr(job, "finished", None)
        connect = getattr(finished, "connect", None)
        if not callable(connect) or getattr(job, "_scan_hooked", False):
            return
        try:
            connect(self._release_waiting_scan)
        except TypeError:
            return
        job._scan_hooked = True

    def _release_waiting_scan(self) -> bool:
        """Run a scan that waited out a reply. False means it is still waiting."""
        if not getattr(self, "_scan_when_free", False):
            return False
        if getattr(self, "_speaking", False) or self._model_still_running():
            return False
        self._end_model_turn()
        if self.turns.busy():
            return False
        self._scan_when_free = False
        self._close_followup()
        self._begin_scan()
        return True

    def _arm_yes_no(self, on: bool) -> None:
        listener = getattr(self, "_listener", None)
        if listener is not None:
            listener.expect_yes_no(bool(on))

    def _begin_scan(self) -> None:
        if self._scan_blocked():
            self._defer_scan()
            return
        self._scan_when_free = False
        self._pending_offer = ""
        try:
            result = scan(
                collect_processes(),
                collect_startups(),
                games=self.controller.settings.game_processes,
            )
        except Exception as exc:
            speech = "I couldn't read this PC just now. I did not change anything."
            self.window.health_page.body.setPlainText(speech)
            self.window.home.set_reply("scan", speech, str(exc)[:500])
            self._speak(speech)
            return
        self._suggestions = list(result.suggestions)
        self._suggestion_at = 0
        self._awaiting_more = False
        parts: list[str] = []
        if result.left_games:
            parts.append("I left games alone.")
        if result.memory_line:
            parts.append(result.memory_line)
        if result.summary:
            parts.append(result.summary)
        self._scan_prefix = (" ".join(parts) + " ") if parts else ""
        if not self._suggestions:
            speech = self._scan_prefix.strip()
            if not result.summary:
                speech = (speech + " I didn't find a heavy app or a startup item I would change.").strip()
            self._scan_prefix = ""
            self._arm_yes_no(False)
            self.window.health_page.body.setPlainText(speech)
            self.window.home.set_reply("scan", speech, "Nothing was changed.")
            self._speak(speech)
            return
        self._speak_current_suggestion()

    def _speak_current_suggestion(self) -> None:
        item = self._suggestions[self._suggestion_at]
        speech = self._scan_prefix + item.speech
        self._scan_prefix = ""
        self.window.health_page.body.setPlainText(speech + "\n\nSay yes, or say no.")
        self.window.home.set_reply("scan", speech, "Nothing changes until you say yes.")
        self._arm_yes_no(True)
        self._speak(speech)

    def _answer_suggestion(self, answer: str) -> None:
        item = self._suggestions[self._suggestion_at]
        if answer == "yes":
            result = self._apply_suggestion(item)
        else:
            result = "Leaving it."
        self._suggestion_at += 1
        if self._suggestion_at < len(self._suggestions):
            nxt = self._suggestions[self._suggestion_at]
            speech = f"{result} {nxt.speech}"
            detail = nxt.speech
            self._arm_yes_no(True)
        else:
            speech = f"{result} That's everything I would change."
            self._suggestions = []
            detail = "Nothing else was changed."
            self._arm_yes_no(bool(getattr(self, "_awaiting_more", False)))
        self.window.health_page.body.setPlainText(speech)
        self.window.home.set_reply(answer, speech, detail)
        self._speak(speech)

    def _apply_suggestion(self, item) -> str:
        if item.kind == "close_app":
            speech = close_named(item.name, pids=pids_named, terminate=terminate_pid)
            if speech.startswith("Closed"):
                self._soft_undo = {"kind": "close", "until": time.time() + 10}
            return speech
        if item.kind == "startup":
            speech, previous = apply_startup(item, self._startup_store)
            if previous is not None:
                self._soft_undo = {
                    "kind": "startup",
                    "until": time.time() + 10,
                    "name": item.name,
                    "command": previous,
                }
            return speech
        return "I left it."

    def _google_from_button(self, kind: str) -> None:
        self._start_google(kind or "mail", speak_errors=True)

    def _start_google(self, kind: str, *, speak_errors: bool, only_new: bool = False) -> None:
        self._google_speak_errors = speak_errors
        self._google_only_new = only_new
        if not self.controller.settings.google_enabled:
            self._show_google(
                "Google mail and calendar are off. Turn them on under Tools. Nothing was sent.",
                speak=speak_errors,
            )
            return
        if not self.google_vault.available:
            self._show_google("Saving a Google token needs Windows. Nothing was sent.", speak=speak_errors)
            return
        try:
            token = self._token_for_google()
        except SecretsError as exc:
            self._show_google(str(exc), speak=speak_errors)
            return
        if not token:
            self._show_google(
                "There is no Google token saved. Paste a read-only token under Tools. Nothing was sent.",
                speak=speak_errors,
            )
            return
        running = getattr(self, "_google_job", None)
        if running is not None and running.isRunning():
            self._show_google("I'm already checking Google.", speak=True)
            return
        if only_new:
            job = _GooglePollJob(token, self._seen_google)
            self._google_job = job
            job.ready.connect(self._google_poll_ready)
        else:
            job = _GoogleJob(token, kind)
            self._google_job = job
            job.ready.connect(self._google_ready)
            self.window.tools_page.show_google("Checking Google. Only mail and calendar are read.")
        job.start()

    def _google_ready(self, speech: str) -> None:
        failed = speech.startswith("Google did not") or speech.startswith("Google refused") or speech.startswith("Google sent")
        speak = (self._google_speak_errors or not failed) and not self.turns.busy()
        self._show_google(speech, speak=speak)

    def _show_google(self, speech: str, *, speak: bool) -> None:
        self.window.tools_page.show_google(speech)
        detail = "Nothing was sent." if "Nothing was sent" in speech else "Read only. The token stays out of the log."
        self.window.home.set_reply("google", speech, detail)
        if speak:
            self._speak(speech)

    def _load_seen_google(self) -> None:
        path = data_dir() / "google_seen.json"
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return
        if isinstance(raw, list):
            self._seen_google = {str(item) for item in raw if isinstance(item, str)}

    def _save_seen_google(self) -> None:
        path = data_dir() / "google_seen.json"
        kept = list(self._seen_google)[-200:]
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(kept), encoding="utf-8")
        temporary.replace(path)

    def _token_for_google(self) -> str | None:
        bundle = self.google_vault.load_bundle()
        if not bundle:
            return None
        refresh = str(bundle.get("refresh_token") or "")
        client_id = self.controller.settings.google_client_id
        if refresh and client_id and int(bundle.get("expires_at") or 0) < time.time() + 60:
            try:
                refreshed = refresh_access(client_id, refresh)
            except GoogleError:
                return str(bundle.get("access_token") or "") or None
            self.google_vault.save_bundle(refreshed)
            return str(refreshed.get("access_token") or "") or None
        return str(bundle.get("access_token") or "") or None

    def _google_poll_ready(self, speech: str, seen: list) -> None:
        if speech.startswith("New from Google"):
            self._seen_google = set(seen)
            self._save_seen_google()
            self._show_google(speech, speak=not self.turns.busy())
            return
        if self._google_speak_errors and speech:
            self._show_google(speech, speak=not self.turns.busy())

    def _google_sign_in(self, client_id: str) -> None:
        from babysitter.plugins.tools.google_account import clean_client_id
        from babysitter.secrets import SecretsError as _SecretsError

        page = self.window.tools_page
        try:
            cleaned = clean_client_id(client_id)
        except _SecretsError as exc:
            page.show_google(str(exc))
            return
        self.controller.settings.google_client_id = cleaned
        save_settings(self.controller.settings)
        verifier, challenge = pkce_pair()
        state = verifier[:16]
        url = authorization_url(cleaned, state, challenge)
        job = _SignInJob(cleaned, verifier, state, url)
        self._sign_in_job = job
        job.open_browser.connect(lambda link: QDesktopServices.openUrl(QUrl(link)))
        job.finished_ok.connect(self._google_signed_in)
        job.failed.connect(page.show_google)
        job.start()
        page.show_google("Waiting for Google in your browser. Read-only mail and calendar only.")

    def _google_signed_in(self) -> None:
        job = getattr(self, "_sign_in_job", None)
        bundle = getattr(job, "bundle", None)
        if job is not None:
            job.bundle = None
        if not bundle:
            self.window.tools_page.show_google("Google sign-in did not return a token. Nothing was saved.")
            return
        try:
            self.google_vault.save_bundle(bundle)
        except SecretsError as exc:
            self.window.tools_page.show_google(str(exc))
            return
        self.window.tools_page.set_google_saved(True, self.google_vault.available)
        self.window.tools_page.show_google(
            "Signed in. The token is encrypted on this PC. BabySitter can refresh it. Nothing was sent except the sign-in."
        )

    def _save_google_token(self, raw: str) -> None:
        page = self.window.tools_page
        try:
            self.google_vault.save(raw)
        except SecretsError as exc:
            saved = self.google_vault.has_token() if self.google_vault.available else False
            page.set_google_saved(saved, self.google_vault.available)
            page.show_google(str(exc))
            return
        page.set_google_saved(True, self.google_vault.available)
        page.show_google("The token is saved. It is not shown again, and it is not stored in settings.json.")

    def _delete_google_token(self) -> None:
        page = self.window.tools_page
        if not ask_yes_no(
            self.window,
            "Delete the saved Google token?",
            "This removes the encrypted token from this PC. Mail and calendar checks stop until you save one again.",
            "Delete the token",
            "Keep it",
        ):
            return
        try:
            self.google_vault.delete()
        except SecretsError as exc:
            page.show_google(str(exc))
            return
        page.set_google_saved(False, self.google_vault.available)
        page.show_google("The token is deleted. Nothing was sent.")

    def _timer_finished(self, label: str, item_id: str = "") -> None:
        self._active_timer = None
        self._undo_until = 0
        words = label
        if item_id:
            items = load_list("schedule.json")
            target = next((item for item in items if str(item.get("id") or "") == item_id), None)
            if target is None or str(target.get("fired") or "") == "yes":
                return
            target["fired"] = "yes"
            save_list("schedule.json", items)
            self.window.schedule_page.refresh()
            words = str(target.get("text") or label)
        speech = f"Reminder. {words}"
        self.window.home.set_reply(
            "reminder",
            speech,
            "Said on this PC while BabySitter is open. The AI can be off. Nothing was sent.",
        )
        self.tray.notify("Reminder", speech)
        self._speak(speech, alert=True)

    def _save_followup(self, text: str) -> None:
        try:
            seconds = int(text.split()[1])
        except (IndexError, ValueError):
            return
        seconds = max(5, min(20, seconds))
        self.controller.settings.followup_seconds = seconds
        save_settings(self.controller.settings)
        self.window.voice_page.status.setText(f"Follow-up listening is {seconds} seconds. Saved on this PC.")

    def _save_proactivity(self, text: str) -> None:
        try:
            level = int(text.split()[1])
        except (IndexError, ValueError):
            return
        self.controller.settings.proactivity = max(0, min(3, level))
        save_settings(self.controller.settings)
        self.window.voice_page.status.setText(
            f"Proactivity is {self.controller.settings.proactivity}. Saved on this PC."
        )

    def _save_rating(self, label: str) -> None:
        try:
            record_rating(label)
        except ValueError:
            return
        speech = "Saved. I'll use that the next time the AI turns on."
        self.window.voice_page.status.setText(speech)
        self.window.home.set_reply("rating", speech, "The tone stays fixed until the next time you turn the AI on.")
        self._speak(speech)

    def _speak_weekly(self) -> None:
        if self.turns.busy():
            self.window.home.set_phase("on", "The weekly review waits until this reply finishes.")
            return
        memories = [str(item.get("text") or "") for item in load_list("memory.json")]
        notes = [str(item.get("content") or "") for item in self._history if item.get("role") == "user"]
        speech = weekly_review(memories, notes)
        from datetime import date

        self.controller.settings.last_weekly_review = date.today().isoformat()
        save_settings(self.controller.settings)
        self.window.home.set_reply("weekly review", speech, "Written on this PC. The model was not asked.")
        self._speak(speech)

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
        if self.turns.busy() or (running_voice is not None and running_voice.isRunning()):
            self.window.models_page.body.setPlainText(
                "A reply is in progress. The benchmark waits so it does not load the card again."
            )
            return
        job = _BenchJob(self.controller.ollama, mode.model, mode.num_ctx, mode.num_batch)
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

    def _unpin_card(self, pin_id: str) -> None:
        if not pin_id:
            return
        remove_item("pins.json", pin_id)
        self._refresh_pins()
        self.controller._remember("Unpinned a card. Nothing else was deleted.")
        self.window.home.set_history(self.controller.history)

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
        if decision == "wait":
            return
        self._release_local_voice()
        if decision == "quit":
            self._finish_quit()
            return
        self.controller.quit_after_stopping()

    def _on_hidden_to_tray(self) -> None:
        """The X button hides the window. The model does not stay loaded behind it."""
        self._release_local_voice()
        if self._ai_is_resident():
            self.controller.turn_off(emergency=False, tray_choice="close")
            self.window.home.set_phase(self.controller.state, "The window is hidden. The AI is turning off.")
            return
        self.window.home.set_phase("off", "The window is hidden. The AI is off. Nothing is listening.")

    def _ai_is_resident(self) -> bool:
        ollama = self.controller.ollama
        port_open = False
        try:
            port_open = bool(ollama.port_open())
        except OSError:
            port_open = False
        return self.controller.state != "off" or port_open or bool(getattr(ollama, "we_started_server", False))

    def _release_local_voice(self) -> None:
        """Drop the speech models and close the microphone. The files stay on disk."""
        try:
            release_model()
        except Exception:
            pass
        try:
            release_kokoro()
        except Exception:
            pass
        listener = getattr(self, "_listener", None)
        if listener is not None:
            listener.stop()
        recorder = getattr(self, "_recorder", None)
        if recorder is not None:
            try:
                recorder.close()
            except Exception:
                pass

    def _finish_quit(self) -> None:
        self._release_local_voice()
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
