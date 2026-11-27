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

from babysitter.phrasing import PhraseBook
from babysitter.ui.jobs import retain_until_finished, take_turn

from babysitter.commands import HELP_DETAIL, HELP_SPEECH, QuickCommand, match_quick_command, spoken_when, timer_label
from babysitter.filefind import (
    CACHE_SECONDS,
    default_folders,
    match_files,
    open_found,
    recently_opened,
    scan_folders,
    search_reply,
    sounds_like_a_question,
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
from babysitter.selfupdate import spawn_finish_update
from babysitter.updates import (
    PreparedUpdate,
    UpdateError,
    UpdatePlan,
    check_for_update,
    prepare_update,
)
from babysitter.controller import Controller, windows_registrar_or_dummy
from babysitter.deskstore import add_item, hero_path, load_list, remove_item, save_list
from babysitter.intelligence import get_mode
from babysitter.ollama import OllamaError
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
    more_answer,
    unread_detail,
    remainder_after,
    remembered_reply,
    sapi_rate,
    speakable,
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
    collect_startups,
    pids_named,
    running_game_names,
    scan,
    spoken_reading,
    suggestion_answer,
    terminate_pid,
    windows_startup_store,
)
from babysitter.blackboard import (
    FeedError,
    default_feed_vault,
)
from babysitter.paths import google_school_token_path
from babysitter.plugins.tools.google_account import (
    DpapiGoogleVault,
    GoogleError,
    authorization_url,
    default_google_vault,
    exchange_code,
    fresh_lines,
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
    phrase = Signal(str, object)
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
    def __init__(self, busy, voice_name: str = "") -> None:
        super().__init__()
        self._busy = busy
        self._voice = voice_name

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

            from babysitter.plugins.voice.engines import is_natural

            if is_natural(self._voice):
                # A natural voice takes about 20 seconds to load; do it now, not at the first reply.
                from babysitter.plugins.voice import engines
                from babysitter.plugins.voice.clone_voice import warm as warm_natural

                pack = engines.EXTRA_VOICES.get(self._voice)
                if pack is not None:
                    warm_natural(pack[1], engines.free_mib_hint())
            warm()
            if self._busy() or not ready():
                return

            def render(text: str):
                from babysitter.plugins.voice.kokoro_voice import render_clip

                return render_clip(text, self._voice)

            # Fillers only for a Kokoro voice; the Windows voice has none.
            if self._voice and not self._voice.startswith("Microsoft"):
                library(self._voice).prepare(render, self._busy)
        except Exception:
            return


def _png_base64(picture: QPixmap) -> str:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    picture.save(buffer, "PNG")
    return base64.b64encode(bytes(buffer.data())).decode("ascii")


class _BenchJob(QThread):
    finished_text = Signal(str)

    def __init__(self, ollama, model: str, num_ctx: int, num_batch: int = 512, keep_alive="5m") -> None:
        super().__init__()
        self._ollama = ollama
        self._model = model
        self._num_ctx = num_ctx
        self._num_batch = num_batch
        self._keep_alive = keep_alive

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
                    keep_alive=self._keep_alive,
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
        context_note: str = "",
        note_more=None,
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
        self._context_note = context_note
        self._note_more = note_more
        self.cancel = threading.Event()
        self.turn = 0

    def run(self) -> None:
        prompt = self._prompt
        self._prompt = ""
        parts: list[str] = []
        sent_lead = False
        sent_token = False
        note = self._context_note
        more = ""
        if self._note_more is not None:
            try:
                more = self._note_more() or ""
            except Exception:
                more = ""
        if more:
            note = f"{note}\n{more}".strip() if note else more
        extra = {"context_note": note} if note else {}
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
                **extra,
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
        for piece in speech_chunks(speakable(text), limit=self._limit):
            self.incoming.put(piece)

    def close_input(self) -> None:
        """No more sentences are coming. The voice finishes what it has."""
        self.incoming.put(None)

    def run(self) -> None:
        text = self._text
        self._text = ""
        prefs = self._prefs
        try:
            # The voice hears "3.7 gigabytes"; the screen keeps "3.7 GB".
            # The processor and natural voices make a whole piece before any of
            # it plays, so the first piece is kept short (see QUICK_FIRST).
            pieces = speech_chunks(speakable(text), limit=self._limit, quick_start=prefs.get("engine") != "windows")
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
            elif prefs.get("engine") == "extra":
                from babysitter.plugins.voice.engines import render as render_extra
                from babysitter.plugins.voice.kokoro_voice import speak_sequence

                voice, speed = prefs.get("name", ""), max(0.5, int(prefs.get("speed", 100)) / 100)
                speak_sequence(
                    pieces,
                    voice,
                    int(prefs.get("speed", 100)),
                    0,
                    on_start=self.started.emit,
                    on_piece=self.phrase_done.emit,
                    incoming=self.incoming,
                    render=lambda piece, voice=voice, speed=speed: render_extra(voice, piece, speed),
                )
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

    def __init__(self, wav: bytes, engine: str = "whisper") -> None:
        super().__init__()
        self._wav = wav
        self._engine = engine

    def run(self) -> None:
        wav = self._wav
        self._wav = b""
        if self._engine in {"moonshine", "parakeet"}:
            from babysitter.plugins.voice.engines import EngineError, hear
            from babysitter.plugins.voice.hearing import Transcript

            try:
                self.result = Transcript(hear(self._engine, wav), True)
                self.heard.emit(self.result.text)
            except EngineError as exc:
                self.failed.emit(str(exc))
            except Exception:
                self.failed.emit("Could not turn that recording into text. Nothing was sent.")
            finally:
                wav = b""
            return
        try:
            from babysitter.plugins.voice.hearing import needs_second_pass, pick_pass, read_speech

            first = read_speech(wav, beam_size=1)
            second = read_speech(wav, beam_size=5) if needs_second_pass(first) else None
            self.result = pick_pass(first, second)
            self.heard.emit(self.result.text)
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


class _ScanJob(QThread):
    """Reads the PC for "scan my PC": processes, startup items, Defender.

    The processor share needs a second of watching and Defender takes a
    few more, so this is off the window's thread. It only reads.
    """

    finished_scan = Signal(object)

    def __init__(self, games: list[str]) -> None:
        super().__init__()
        self._games = list(games)

    def run(self) -> None:
        from babysitter.pcreport import (
            collect_rows,
            defender_threats,
            report_detail,
            report_speech,
            suspicious,
            top_apps,
        )
        from babysitter.pcscan import own_pids

        try:
            rows = collect_rows()
            startups = collect_startups()
            games = list(self._games)
            try:
                games.extend(running_game_names())
            except Exception:
                pass
            mine = own_pids()
            result = scan([(row.name, row.rss, row.pid) for row in rows], startups, games=games)
            apps = top_apps(rows, skip_pids=mine)
            flags = suspicious(rows, startups, skip_pids=mine)
            threats = defender_threats()
            report = (report_speech(apps, flags, threats), report_detail(apps, flags, threats))
        except Exception as exc:
            self.finished_scan.emit(exc)
            return
        self.finished_scan.emit((result, report))


class _NaturalSetupJob(QThread):
    """The helper's own Python, the Chatterbox model, and the narrator clips, after a yes."""

    step = Signal(str)

    def run(self) -> None:
        from babysitter import narrators
        from babysitter.modelpacks import PackError, download, ready
        from babysitter.platform import run_hidden
        from babysitter.plugins.voice import clone_voice

        try:
            if not clone_voice.environment_ready():
                for index, command in enumerate(clone_voice.install_steps(), start=1):
                    self.step.emit(f"Setting up the natural voices, step {index} of 3. This takes a few minutes…")
                    done = run_hidden(command, timeout=3600)
                    if done.returncode not in (0, None):
                        self.step.emit("The natural voices could not be set up. Step " + str(index) + " failed; the log has the details.")
                        return
            if not ready("chatterbox"):
                self.step.emit("Downloading the Chatterbox voice model, about 3.2 GB…")
                download("chatterbox")
            for narrator in narrators.NARRATORS:
                if not narrators.clip_ready(narrator):
                    self.step.emit(f"Fetching {narrator.name}…")
                    narrators.download(narrator)
        except (PackError, narrators.NarratorError) as exc:
            self.step.emit(str(exc))
            return
        except Exception:
            self.step.emit("The natural voices stopped before they were ready. Nothing half-done is used.")
            return
        self.step.emit("The natural voices are ready. Each download was checked against its recorded hash.")


class _PackDownloadJob(QThread):
    """One model pack, after a yes. Checked against its hash before it is kept."""

    done = Signal(str)

    def __init__(self, pack_id: str) -> None:
        super().__init__()
        self._pack = pack_id

    def run(self) -> None:
        from babysitter.modelpacks import PackError, download

        try:
            self.done.emit(download(self._pack))
        except PackError as exc:
            self.done.emit(str(exc))
        except Exception:
            self.done.emit("The download stopped before it finished. Nothing was kept.")


class _HealthJob(QThread):
    """The read-only PC check. Get-CimInstance can take seconds, so it runs
    here instead of freezing the window."""

    finished_text = Signal(str)

    def run(self) -> None:
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
            self.finished_text.emit(f"The check could not run ({exc}). Nothing was changed.")
            return
        text = ((completed.stdout or "") + (completed.stderr or "")).strip()
        self.finished_text.emit(text or "The check returned nothing. Nothing was changed.")


class _LinkedJob(QThread):
    """One read of every linked account, off the window's thread.

    The Tools list, the spoken summary, and the 15-minute check all use it.
    Tokens are fetched here too, so refreshing a sign-in never freezes the window.
    """

    ready = Signal(object)

    def __init__(self, accounts, feed, want_fresh: bool = False) -> None:
        super().__init__()
        self._accounts = list(accounts)
        self._feed = feed
        self._want_fresh = want_fresh

    def run(self) -> None:
        from babysitter.inbox import Inbox, gather

        try:
            result = gather(self._accounts, self._feed, want_fresh=self._want_fresh)
        except Exception:
            result = Inbox(problems=["The linked accounts did not answer. Nothing was changed."])
        self._accounts = []
        self._feed = None
        self.ready.emit(result)


# The conversation sent with each question: up to HISTORY_MAX lines, cut back
# to HISTORY_KEEP in one step. Dropping the oldest two lines on every turn
# changed the start of the prompt each time, so Ollama could not reuse what
# it had already read and went through the whole conversation again before
# each answer. Cut in steps, the start stays the same for four exchanges.
HISTORY_MAX = 20
HISTORY_KEEP = 12


def trim_history(history: list) -> None:
    if len(history) > HISTORY_MAX:
        del history[:-HISTORY_KEEP]


class _CallJob(QThread):
    """One call that may reach the network, off the window's thread. Returns (result, problem)."""

    ready = Signal(object, str)

    def __init__(self, call) -> None:
        super().__init__()
        self._call = call

    def run(self) -> None:
        try:
            result = self._call()
        except Exception as exc:  # noqa: BLE001 - every error here carries a plain message
            message = str(exc) or "That did not work. Nothing was changed."
            self.ready.emit(None, message)
        else:
            self.ready.emit(result, "")
        finally:
            self._call = None


class _DriveTextJob(QThread):
    """Find one Drive file by name and read it as plain text, off the window's thread."""

    ready = Signal(str, str, str)  # name, text, problem

    def __init__(self, token_for, name: str) -> None:
        super().__init__()
        self._token_for = token_for
        self._name = name

    def run(self) -> None:
        from babysitter.plugins.tools.google_account import (
            DRIVE_TEXT_TYPES,
            GoogleError,
            drive_file_text,
            drive_search_url,
            http_get_json,
        )

        try:
            token = self._token_for()
            if not token:
                raise GoogleError("Google is not signed in. Sign in on Settings, Accounts and home.")
            payload = http_get_json(drive_search_url(self._name), token)
            files = [item for item in (payload.get("files") or []) if isinstance(item, dict)]
            if not files:
                raise GoogleError(f"No Drive file has {self._name} in its name.")
            readable = [item for item in files if str(item.get("mimeType") or "") in DRIVE_TEXT_TYPES]
            if not readable:
                raise GoogleError(
                    f"{files[0].get('name') or 'That file'} is not a Google Doc, Word file, or text file, so it was not read."
                )
            item = readable[0]
            self.ready.emit(str(item.get("name") or "the file"), drive_file_text(item, token), "")
        except GoogleError as exc:
            self.ready.emit("", "", str(exc))
        except Exception:  # noqa: BLE001
            self.ready.emit("", "", "Drive did not answer. Nothing was changed.")
        finally:
            self._token_for = None


class _DraftJob(QThread):
    ready = Signal(str, str)

    def __init__(self, tokens: list, window_title: str) -> None:
        super().__init__()
        self._tokens = list(tokens)  # tokens, or functions that fetch one
        self._title = window_title

    def run(self) -> None:
        title = self._title
        tokens: list[str] = []
        for item in self._tokens:
            try:
                token = item() if callable(item) else item
            except Exception:
                continue
            if token:
                tokens.append(str(token))
        self._tokens = []
        self._title = ""
        from babysitter.writing import read_open_draft

        try:
            draft = read_open_draft(tokens, title, allow_stale=True, limit=4000)
        except Exception:
            draft = None
        if draft is None:
            speech, note = (
                "I don't see a Google Doc on the linked account. Open the doc you are writing, or edit it, and ask again.",
                "",
            )
        else:
            speech, note = draft.speech, draft.note
            if any(token and (token in speech or token in note) for token in tokens):
                speech = note = "The Google Doc could not be shown."
        for index in range(len(tokens)):
            tokens[index] = ""
        self.ready.emit(speech, note)


class _MicrosoftSignInJob(QThread):
    """Microsoft's sign-in page, then one local page on port 8765 for the code."""

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
        from babysitter.plugins.tools.microsoft_account import MicrosoftError, exchange_code

        try:
            code = listen_for_code(self._state, on_ready=lambda: self.open_browser.emit(self._url))
            self.bundle = exchange_code(self._client_id, code, self._verifier)
        except GoogleError as exc:
            self.failed.emit(str(exc).replace("Google", "Microsoft"))
            return
        except MicrosoftError as exc:
            self.failed.emit(str(exc))
            return
        except Exception:
            self.failed.emit("Microsoft sign-in stopped before it finished. Nothing was saved.")
            return
        self.finished_ok.emit()


class _SignInJob(QThread):
    open_browser = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, client_id: str, verifier: str, state: str, url: str, client_secret: str = "") -> None:
        super().__init__()
        self._client_secret = client_secret
        self._client_id = client_id
        self._verifier = verifier
        self._state = state
        self._url = url
        self.bundle: dict | None = None

    def run(self) -> None:
        try:
            code = listen_for_code(self._state, on_ready=lambda: self.open_browser.emit(self._url))
            self.bundle = exchange_code(self._client_id, code, self._verifier, client_secret=self._client_secret)
            self.finished_ok.emit()
        except GoogleError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Google sign-in did not finish. Nothing was saved.")
        finally:
            self._verifier = ""


class _UpdateCheckJob(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            plan = check_for_update()
            self.ready.emit(plan)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Update check stopped before finishing ({exc}).")


class _UpdateApplyJob(QThread):
    step = Signal(str)
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, plan: UpdatePlan) -> None:
        super().__init__()
        self._plan = plan

    def run(self) -> None:
        try:
            prepared = prepare_update(self._plan, on_step=self.step.emit)
            self.ready.emit(prepared)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Update stopped before finishing ({exc}).")


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
        controller.reply_busy = self._reply_busy
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
        self.google_school_vault = DpapiGoogleVault(google_school_token_path())
        self.blackboard_vault = default_feed_vault()
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
        self._google_poll.timeout.connect(self._warn_google_week)
        # Phase 5: the same 15-minute read while the AI is off, said in the Windows voice.
        self._off_poll = QTimer(self.window)
        self._off_poll.setInterval(15 * 60 * 1000)
        self._off_poll.timeout.connect(self._check_while_off)
        QTimer.singleShot(60 * 1000, self._sync_off_alerts)
        QTimer.singleShot(8000, self._warn_google_week)  # once soon after opening, too
        self._search_job: _SearchJob | None = None
        self.single_instance = None
        self._last_update_plan: UpdatePlan | None = None
        self._pending_relaunch: PreparedUpdate | None = None
        self._update_prompt_install = False
        self._update_speak_result = False
        self._power_ready = False
        self._turn_id = 0
        self._responsiveness = ResponsivenessLog()
        self._phrases = PhraseBook()
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
        # v3: the pill opens the state menu, which holds the power button.
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
        self.controller.ollama_offer.connect(self._on_outside_ollama)
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
        settings.alerts_when_off.toggled.connect(self._set_alerts_when_off)
        settings.save_conversations.toggled.connect(lambda on: self._set_flag("save_conversations", on))
        settings.side_button.toggled.connect(lambda on: self._set_flag("side_button", on))
        settings.searx_enabled.toggled.connect(lambda on: self._set_flag("searx_enabled", on))
        settings.weather_save.clicked.connect(lambda: self._save_town(settings.weather_town.text()))
        settings.home_save.clicked.connect(self._save_home_clicked)
        settings.quiet_save.clicked.connect(self._save_quiet_hours)
        settings.microphone_chosen.connect(self._set_microphone)
        settings.hearing_chosen.connect(self._set_hearing_engine)
        settings.context_chosen.connect(self._set_context)
        self.window.voice_page.pack_needed.connect(self._offer_pack)
        self.window.voice_page.voice_saved.connect(self._voice_saved)
        self.window.voice_page.record_own.connect(self._record_own_voice)
        self.window.voice_page.delete_own.connect(self._delete_own_voice)
        self.controller.voice_wants_card = self._natural_voice_chosen
        from babysitter.plugins.voice import engines as _engines

        _engines.free_mib_hint = self._free_video_mib
        settings.refresh_microphones.clicked.connect(self._fill_microphones)
        settings.searx_save.clicked.connect(self._save_searx_port)
        settings.check_updates.clicked.connect(self._check_updates)
        settings.install_update.clicked.connect(self._install_update_clicked)
        self._hide_charts = _HideCharts(self.controller.probe)
        self.window.installEventFilter(self._hide_charts)
        settings.emergency_change.clicked.connect(self._change_emergency)
        settings.power_change.clicked.connect(self._change_power_key)
        settings.add_game.clicked.connect(self._add_running_game)
        settings.add_typed.clicked.connect(self._add_typed_game)
        settings.type_game.returnPressed.connect(self._add_typed_game)
        settings.remove_game.clicked.connect(self._remove_game)
        settings.add_excluded.clicked.connect(self._add_journal_excluded)
        settings.type_excluded.returnPressed.connect(self._add_journal_excluded)
        settings.remove_excluded.clicked.connect(self._remove_journal_excluded)
        self.window.journal_page.enabled.toggled.connect(self._set_journal_enabled)
        self.window.journal_page.notice.connect(self._on_page_notice)
        self.window.files_page.notice.connect(self._on_page_notice)
        settings.wipe_journal.clicked.connect(self._wipe_journal)
        settings.add_search_folder.clicked.connect(self._add_search_folder)
        settings.remove_search_folder.clicked.connect(self._remove_search_folder)
        settings.open_data.clicked.connect(lambda: open_folder(self.controller.data_folder()))
        settings.backup.clicked.connect(self._back_up_memory)
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
        tools.google_sign_in_requested.connect(lambda client: self._google_sign_in(client, "personal"))
        tools.google_client_file_requested.connect(self._choose_google_client_file)
        tools.microsoft_sign_in_requested.connect(self._microsoft_sign_in)
        tools.microsoft_sign_out_requested.connect(self._microsoft_sign_out)
        tools.microsoft_client.setText(self.controller.settings.microsoft_client_id)
        tools.school_sign_in_requested.connect(lambda client: self._google_sign_in(client, "school"))
        tools.inbox_refresh.connect(self._refresh_inbox)
        tools.blackboard_save.connect(self._save_blackboard)
        tools.blackboard_enabled_changed.connect(self._set_blackboard)
        tools.google_client.setText(self.controller.settings.google_client_id)
        tools.set_blackboard_enabled(self.controller.settings.blackboard_enabled)
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
        home.fresh_start.connect(self._fresh_start)
        home.pin_lock.connect(self._lock_pin)
        home.pin_restore.connect(self._restore_pin)
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
        self._reminder_timer.setInterval(1000)
        self._reminder_timer.timeout.connect(self._tick_reminders)
        self._reminder_timer.start()
        self._show_reminder_clock()

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
        linked = settings.google_enabled or settings.microsoft_enabled
        self.window.home.set_privacy(settings.social_search_enabled, linked)
        self.window.set_privacy(settings.social_search_enabled or linked)

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
        self._store_job("_search_job", job)
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

    def _local_control(self, quick) -> tuple[str, str]:
        """Help, voice speed, volume, and power by voice, answered here (0.29.0).

        Before, these went to the model, which cannot change any of them, so it
        said "Sure, I'll slow down" and nothing changed, or made up abilities.
        """
        state = self.controller.state
        if quick.kind == "help":
            return HELP_SPEECH, HELP_DETAIL
        if quick.kind == "volume":
            return (
                "I can't change the volume myself. Use your volume keys, or the speaker icon on the taskbar.",
                "BabySitter's voice follows the Windows volume.",
            )
        if quick.kind == "voice_speed":
            path = data_dir() / "voice.json"
            saved: dict = {}
            try:
                loaded = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
                saved = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError):
                saved = {}
            try:
                speed = int(saved.get("speed", 105))
            except (TypeError, ValueError):
                speed = 105
            wanted = max(80, min(130, speed + int(quick.seconds)))
            if wanted == speed:
                edge = "slowest" if quick.seconds < 0 else "fastest"
                return f"That's already my {edge} setting.", "Voice speed goes from 80 to 130 on the Voice page."
            saved["speed"] = wanted
            saved.setdefault("voice", self._voice_prefs().get("name") or "Heart & Sarah blend")
            from babysitter.paths import write_text_safely

            write_text_safely(path, json.dumps(saved, indent=2) + "\n")
            try:
                self.window.voice_page.speed[1].setValue(wanted)
            except Exception:  # noqa: BLE001 - the slider is a mirror of the file
                pass
            word = "slower" if quick.seconds < 0 else "faster"
            return f"Okay, a little {word}.", f"Voice speed is now {wanted} (it was {speed}). Saved on this PC."
        if quick.kind == "power_off":
            if state == "off" and not self.controller._busy:
                return "The AI is already off.", ""
            self.controller.turn_off()
            return "Turning the AI off.", "Same as the Off button. Say or press On to start it again."
        if quick.kind == "game_mode":
            if state == "game":
                return "Game mode is already on.", ""
            if state != "on":
                return "The AI is off, so the graphics card is already free.", "Game mode only matters while the AI is on."
            self._return_to_game = False
            timer = getattr(self, "_game_return_timer", None)
            if timer is not None:
                timer.stop()
            self.controller.enter_game()
            return "Game mode. Unloading the model so the graphics card is free.", ""
        if quick.kind == "leave_game":
            if state == "game":
                self._on_game()
                return "Loading the model again.", ""
            if state == "on":
                return "I'm here.", ""
            return "The AI is off. Press On, or the turn-on key, to start it.", ""
        return "", ""

    def _on_game(self) -> None:
        # Game mode or Leave by hand replaces a "Load the brain?" visit. Its
        # 2-minute timer used to survive this and undo Leave later.
        self._return_to_game = False
        timer = getattr(self, "_game_return_timer", None)
        if timer is not None:
            timer.stop()
        if self.controller.state == "game":
            self.controller.wake()
        else:
            self.controller.enter_game()

    def _reply_busy(self) -> bool:
        """An answer is still being written or spoken."""
        turns = getattr(self, "turns", None)
        try:
            writing = bool(turns.busy()) if turns is not None else False
        except Exception:
            writing = False
        return writing or bool(getattr(self, "_speaking", False))

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
        try:
            self._sync_keyword()
        except (ImportError, OSError):
            try:
                from babysitter.logsetup import get_logger

                get_logger().exception("Keyword listening did not start")
            except Exception:
                pass
        if state == "off":
            release_model()
            release_kokoro()
            try:
                from babysitter.plugins.voice.engines import release as release_engines

                release_engines()
            except Exception:
                pass
            self._session_personality = ""
            self._google_notified = False
            self._session_id = ""
            self._google_poll.stop()
            self._sync_off_alerts()
            self._end_model_turn()
            self._return_to_game = False
            timer = getattr(self, "_game_return_timer", None)
            if timer is not None:
                timer.stop()
        if state == "game":
            # The off-time check takes over in game mode (Windows voice, no model),
            # so the AI-on check stops: two 15-minute reads would say the same mail twice.
            self._google_poll.stop()
            # Game mode gives the card back: the natural-voice helper closes too.
            try:
                from babysitter.plugins.voice.engines import release as release_engines

                release_engines()
            except Exception:
                pass
        if state in {"on", "game"}:
            self._sync_off_alerts()
        if state == "on":
            self._session_personality = session_clause()
            self._warm_voice()
            self._warm_hearing()
            self._arm_game_return()
            queued = getattr(self, "_queued_after_load", "")
            linked = self.controller.settings.google_enabled or self.controller.settings.microsoft_enabled
            if queued:
                self._queued_after_load = ""
                self._pending_line = queued
                self._send_heard()
            elif linked and not self._google_notified:
                self._google_notified = True
                self._start_google("both", speak_errors=False, only_new=True)
            # Started on every return to On, back from a game too, and also when
            # a queued question was answered first.
            if linked and not self._google_poll.isActive():
                self._google_poll.start()
        self.window.emergency.setToolTip(
            f"The same as {self.controller.settings.emergency_hotkey}. "
            "Turns the AI fully off, even if this window is hidden."
        )

    def _reply_keep_alive(self):
        """How long the model stays loaded after a reply.

        While the AI is on, it stays loaded, so a question after a quiet spell
        does not wait for the model to load again (several seconds). It is
        still unloaded at Off, at closing, and by game mode. When BabySitter
        started Ollama, Windows also ends Ollama if BabySitter itself ends, so
        nothing is left behind. An Ollama it did not start gets 30 minutes.
        """
        if getattr(self, "_return_to_game", False):
            return "2m"
        if getattr(self.controller.ollama, "we_started_server", False):
            return -1
        return "30m"  # the same as OllamaClient.on_keep_alive

    def _hearing_engine(self) -> str:
        """The engine that hears the question. A chosen one not downloaded yet falls back to Whisper."""
        from babysitter.modelpacks import ready as pack_ready

        engine = self.controller.settings.hearing_engine
        if engine in {"moonshine", "parakeet"} and pack_ready(engine):
            return engine
        return "whisper"

    def _hearing_ready(self) -> bool:
        if self._hearing_engine() != "whisper":
            return True
        return packages_installed() and model_ready()

    def _set_hearing_engine(self, engine: str) -> None:
        from babysitter.modelpacks import ready as pack_ready

        self.controller.settings.hearing_engine = engine if engine in {"whisper", "moonshine", "parakeet"} else "whisper"
        save_settings(self.controller.settings)
        if engine in {"moonshine", "parakeet"} and not pack_ready(engine):
            self._offer_pack(engine)
            return
        from babysitter.plugins.voice.engines import HEARING_ENGINES

        self.window.voice_page.status.setText(f"{HEARING_ENGINES.get(engine, 'Whisper')} hears your questions now.")

    def _natural_voice_chosen(self) -> bool:
        from babysitter.plugins.voice.engines import is_natural

        return is_natural(self._voice_prefs().get("name", ""))

    def _free_video_mib(self):
        snap = getattr(self.controller, "latest_status", None)
        gpu = getattr(snap, "gpu", None)
        if gpu is None:
            return None
        return int(gpu.total_mib) - int(gpu.used_mib)

    def _voice_saved(self, name: str) -> None:
        """A natural voice shares the card, so a model on Medium or High moves to Low."""
        from babysitter.plugins.voice.engines import is_natural

        if is_natural(name) and self.controller.state == "on" and self.controller.loaded_level != "low":
            self.controller._remember("A natural voice is chosen, so the AI moves to Low and both fit on the graphics card.")
            self.controller.reload_model("low")

    def _offer_natural_voices(self) -> None:
        """One yes sets up the helper, the Chatterbox model, and every narrator's clip."""
        running = getattr(self, "_natural_job", None)
        if running is not None and running.isRunning():
            self.window.voice_page.status.setText("The natural voices are already being set up.")
            return
        if not ask_yes_no(
            self.window,
            "Set up the natural voices?",
            "About 6 GB, once: PyTorch for your graphics card (about 2.5 GB), the Chatterbox voice model "
            "(3.2 GB, checked against its recorded hashes), and a short clip of each of 8 narrators "
            "(Linda Johnson of LJ Speech, public domain, and 7 Hi-Fi TTS readers, CC BY 4.0). "
            "While a natural voice is chosen, the AI runs on Low so both fit on the card.",
            "Download about 6 GB",
            "Not now",
        ):
            self.window.voice_page.status.setText("The natural voices were not set up. Nothing was downloaded.")
            return
        job = _NaturalSetupJob()
        self._store_job("_natural_job", job)
        job.step.connect(self.window.voice_page.status.setText)
        job.start()

    def _record_own_voice(self) -> None:
        """Consent first, every time; then the recording window. Nothing leaves this PC."""
        from babysitter import ownvoice
        from babysitter.ui.record_voice import RecordVoiceDialog

        status = self.window.voice_page.status
        if not ask_yes_no(self.window, "Record your voice?", ownvoice.CONSENT, "I agree, record my voice", "Not now"):
            status.setText("Nothing was recorded.")
            return
        result = RecordVoiceDialog(self.window, self._mic_device()).run()
        if not result:
            status.setText("Nothing was saved. Your earlier recording, if any, is unchanged.")
            return
        status.setText(result)
        from babysitter.plugins.voice.clone_voice import environment_ready
        from babysitter.modelpacks import ready as pack_ready

        if not (environment_ready() and pack_ready("chatterbox")):
            status.setText(result + " Speaking in it needs the natural voices set up first.")
            self._offer_natural_voices()

    def _delete_own_voice(self) -> None:
        from babysitter import ownvoice

        if not ownvoice.ready():
            self.window.voice_page.status.setText("There is no voice recording to delete.")
            return
        if not ask_yes_no(
            self.window,
            "Delete your voice?",
            "This deletes your voice recording from this PC. If it is the chosen voice, Kokoro speaks instead "
            "until you pick another or record again.",
            "Delete it",
            "Keep it",
        ):
            return
        self.window.voice_page.status.setText(ownvoice.delete())

    def _offer_pack(self, pack_id: str) -> None:
        if pack_id == "own":
            from babysitter.plugins.voice.clone_voice import environment_ready
            from babysitter.modelpacks import ready as pack_ready

            if environment_ready() and pack_ready("chatterbox"):
                self._record_own_voice()
            else:
                self._offer_natural_voices()
            return
        if pack_id == "natural":
            self._offer_natural_voices()
            return
        """Ask before a model pack downloads. Nothing is fetched without a yes."""
        from babysitter.modelpacks import PACKS

        pack = PACKS[pack_id]
        running = getattr(self, "_pack_job", None)
        if running is not None and running.isRunning():
            self.window.voice_page.status.setText("A download is already running.")
            return
        if not ask_yes_no(
            self.window,
            f"Download {pack.label}?",
            f"About {pack.size_mb} MB, saved in your BabySitter folder and checked against its recorded hash. "
            f"It runs on the processor, not the graphics card. {pack.note}".strip(),
            "Download",
            "Not now",
        ):
            self.window.voice_page.status.setText(f"{pack.label} was not downloaded. Nothing was sent.")
            return
        self.window.voice_page.status.setText(f"Downloading {pack.label}, about {pack.size_mb} MB…")
        job = _PackDownloadJob(pack_id)
        self._store_job("_pack_job", job)
        job.done.connect(lambda message: self.window.voice_page.status.setText(message))
        job.start()

    def _warm_hearing(self) -> None:
        if self.turns.busy():
            return
        if self._hearing_engine() != "whisper":
            return  # Whisper is not loaded when another engine hears the question.
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
        self._store_job("_hearing_job", job)
        job.start()

    def _warm_voice(self) -> None:
        if getattr(self, "_warm_job", None) is not None and self._warm_job.isRunning():
            return
        job = _WarmVoiceJob(self.turns.busy, self._voice_prefs().get("name", ""))
        self._store_job("_warm_job", job)
        job.start()

    def _on_status(self, snap) -> None:
        # set_status already looks for Ollama's tray app among the processes.
        tray = bool(self.window.home.set_status(snap))
        self._refresh_game_note()
        self._hide_orb_if_game()
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

    def _on_outside_ollama(self) -> None:
        self.show_window()
        restart = ask_yes_no(
            self.window,
            "Ollama is already running",
            "Ollama's own tray app started it, so BabySitter's settings are not on: the "
            "this-PC-only address, the smaller memory cache, and cloud models off. "
            "Restart it under BabySitter so they apply? Using it as it is works, without them.",
            "Restart it under BabySitter",
            "Use it as it is",
        )
        self.controller.turn_on(ollama_choice="restart" if restart else "use")

    def _on_tray_prompt(self, message: str) -> None:
        self.show_window()
        close_it = ask_yes_no(
            self.window,
            "Ollama's tray app is running",
            message
            + "\n\nLeave it running keeps that copy as it is. BabySitter's settings (this PC only, "
            "the smaller cache, cloud models off) do not apply to it.",
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
        self.window.settings_page.set_context(0, mode_id)

    def _set_context(self, tokens: int) -> None:
        level = self.controller.set_context(tokens)
        self.window.home.set_intelligence(level)
        self.window.settings_page.set_context(self.controller.settings.context_tokens, level)
        self.controller._remember(f"Memory set to {tokens:,} tokens, on {level.capitalize()}.")
        self.window.home.set_history(self.controller.history)

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
            # Asked for by the game's memory use, so it ends when the game closes.
            self.controller.enter_game(auto=True)
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
        self._fill_settings()
        self.window.files_page.set_folders(self._search_places())
        self._scan_cache = None

    def _remove_search_folder(self) -> None:
        item = self.window.settings_page.search_folders.currentItem()
        if item is None:
            return
        name = str(item.data(Qt.UserRole) or item.text())
        if name == "No extra folders yet.":
            return
        self.controller.settings.search_folders = [
            folder for folder in self.controller.settings.search_folders
            if folder.lower() != name.lower()
        ]
        save_settings(self.controller.settings)
        self._fill_settings()
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
        listener.device = self._mic_device()

    def _mic_device(self) -> int | None:
        """The chosen microphone, or None for Windows' default."""
        from babysitter.microphones import device_for

        try:
            return device_for(self.controller.settings.microphone)
        except Exception:
            return None

    def _back_up_memory(self, folder: str | None = None) -> str:
        """Ask where, then write one zip. Returns the sentence shown."""
        from pathlib import Path

        from babysitter.backup import make_backup

        if folder is None:
            from PySide6.QtWidgets import QFileDialog

            start = str(Path.home() / "Documents")
            folder = QFileDialog.getExistingDirectory(self.window, "Where should the backup go?", start)
            if not folder:
                return ""
        try:
            target, count = make_backup(Path(folder))
        except OSError as exc:
            message = f"The backup could not be written ({exc}). Nothing was changed."
        else:
            message = f"Saved {count} files to {target.name}, in {target.parent}. Sign-ins are not in it."
        self.window.settings_page.backup_status.setText(message)
        self.controller._remember(message)
        return message

    def _dead_mic_notice(self, mic: str) -> None:
        self.window.show_notice(
            f"{mic} is sending silence. Pick the microphone you talk into.",
            "Pick a microphone",
            lambda: self.window.show_settings_section("voice"),
        )

    def _mic_name(self) -> str:
        from babysitter.microphones import shown_name

        try:
            return shown_name(self.controller.settings.microphone)
        except Exception:
            return "the microphone"

    def _set_microphone(self, name: str) -> None:
        self.controller.settings.microphone = " ".join((name or "").split())[:200]
        save_settings(self.controller.settings)
        self._apply_listen_policy()
        listener = getattr(self, "_listener", None)
        if listener is not None and listener.running:
            # Reopen keyword listening on the microphone just chosen.
            listener.stop()
            self._sync_keyword()

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
        name = str(item.data(Qt.UserRole) or item.text())
        if name == "No game names yet.":
            return
        self.controller.remove_game(name)
        self._fill_settings()
        self._refresh_game_note()

    def _add_journal_excluded(self) -> None:
        raw = self.window.settings_page.type_excluded.text()
        try:
            self.controller.add_journal_excluded(raw)
        except ValueError as exc:
            show_copyable(self.window, "That program was not added", str(exc))
            return
        self.window.settings_page.type_excluded.clear()
        self._fill_settings()

    def _remove_journal_excluded(self) -> None:
        item = self.window.settings_page.journal_excluded.currentItem()
        if item is None:
            return
        name = str(item.data(Qt.UserRole) or item.text())
        if name == "No programs left out yet.":
            return
        self.controller.remove_journal_excluded(name)
        self._fill_settings()

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
        snap = getattr(self.controller, "latest_status", None)
        detected = snap.detected_game if (snap is not None and settings.detect_games) else None
        hide = should_hide_orb(
            settings.hide_orb_for_games,
            foreground_process_name(),
            settings.game_processes,
            detected_game=detected,
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

    def note_completed_update(self, message: str) -> None:
        self.window.settings_page.update_status.setText(message)
        self.window.home.set_phase(self.controller.state, message)

    def _update_busy(self) -> bool:
        for attr in ("_update_check_job", "_update_apply_job"):
            job = getattr(self, attr, None)
            if job is not None and job.isRunning():
                return True
        return False

    def _check_updates(
        self,
        _checked: bool = False,
        *,
        prompt_install: bool = False,
        speak_result: bool = False,
    ) -> None:
        del _checked
        page = self.window.settings_page
        if self._update_busy():
            page.update_status.setText("An update check or install is already running.")
            return
        self._update_prompt_install = prompt_install
        self._update_speak_result = speak_result
        page.check_updates.setEnabled(False)
        page.install_update.setEnabled(False)
        page.update_status.setText("Checking for updates…")
        job = _UpdateCheckJob()
        self._store_job("_update_check_job", job)
        job.ready.connect(self._on_update_checked)
        job.failed.connect(self._on_update_check_failed)
        job.start()

    def _on_update_check_failed(self, message: str) -> None:
        page = self.window.settings_page
        page.check_updates.setEnabled(True)
        page.install_update.setEnabled(True)
        page.update_status.setText(message)
        if self._update_speak_result:
            self.window.home.set_reply("update", message, "Nothing was changed.")
            self._speak(message)

    def _on_update_checked(self, plan: UpdatePlan) -> None:
        self._last_update_plan = plan
        page = self.window.settings_page
        page.check_updates.setEnabled(True)
        page.install_update.setEnabled(True)
        if plan.can_install:
            page.install_update.setText(f"Update to {plan.target_version}")
        else:
            page.install_update.setText("Update BabySitter")
        page.update_status.setText(plan.summary)
        if self._update_speak_result:
            self.window.home.set_reply("update", plan.summary, "Nothing is changed until you confirm.")
            self._speak(plan.summary)
        if self._update_prompt_install and plan.can_install:
            self._confirm_and_apply_update(plan)

    def _install_update_clicked(self) -> None:
        if self._update_busy():
            self.window.settings_page.update_status.setText("An update is already running.")
            return
        plan = self._last_update_plan
        if plan is not None and plan.can_install:
            self._confirm_and_apply_update(plan)
            return
        self._check_updates(prompt_install=True)

    def _confirm_and_apply_update(self, plan: UpdatePlan) -> None:
        if not ask_yes_no(
            self.window,
            f"Update BabySitter to {plan.target_version}?",
            plan.confirm_body or plan.summary,
            "Update and restart",
            "Not now",
        ):
            self.window.settings_page.update_status.setText("Update cancelled. Nothing was changed.")
            return
        page = self.window.settings_page
        page.check_updates.setEnabled(False)
        page.install_update.setEnabled(False)
        page.update_status.setText("Starting update…")
        self.window.home.set_phase(self.controller.state, "Updating BabySitter…")
        job = _UpdateApplyJob(plan)
        self._store_job("_update_apply_job", job)
        job.step.connect(self._on_update_step)
        job.ready.connect(self._on_update_prepared)
        job.failed.connect(self._on_update_apply_failed)
        job.start()

    def _on_update_step(self, message: str) -> None:
        self.window.settings_page.update_status.setText(message)
        self.window.home.set_phase(self.controller.state, message)

    def _on_update_apply_failed(self, message: str) -> None:
        page = self.window.settings_page
        page.check_updates.setEnabled(True)
        page.install_update.setEnabled(True)
        page.update_status.setText(message)
        self.window.home.set_phase(self.controller.state, message)

    def _on_update_prepared(self, prepared: PreparedUpdate) -> None:
        self._pending_relaunch = prepared
        self.window.settings_page.update_status.setText(prepared.message)
        self.window.home.set_phase(self.controller.state, prepared.message)
        self.controller.force_quit = True
        self._quit()

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
        self._store_job("_embedder_job", job)
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
        if intent.kind == "set_town":
            from babysitter.weather import WeatherError, clean_place

            try:
                place = clean_place(intent.query).title()
            except WeatherError as exc:
                self._speak(str(exc))
                return
            self.controller.settings.weather_place = place
            save_settings(self.controller.settings)
            speech = f"Got it, {place}. Ask me for the weather any time."
            self.window.home.set_reply("town", speech, "Saved on this PC. It is sent only when you ask for the weather and say yes.")
            self._speak(speech)
            return
        if intent.kind == "weather" and not intent.query:
            from dataclasses import replace as _replace

            place = self.controller.settings.weather_place
            if not place:
                speech = "Which town? Say, my town is, and the name. I'll remember it."
                self.window.home.set_reply("weather", speech, "Nothing was sent.")
                self._speak(speech)
                return
            intent = _replace(intent, query=place, ask=f"Check the weather for {place}? The town name goes to Open-Meteo.")
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
        if intent.kind == "weather":
            self._run_weather(intent)
            return
        if intent.kind == "home":
            self._run_house()
            return
        self._prepare_search(intent.action_id, intent.query, already_yes=True)

    def _run_weather(self, intent) -> None:
        """After the yes: the town goes to Open-Meteo, the forecast comes back, and it is said."""
        from babysitter.weather import check

        place, tomorrow = intent.query, intent.action_id == "tomorrow"
        self.window.home.set_reply("weather", f"Checking the weather for {place}…", "Only the town name was sent, to Open-Meteo.")
        job = _CallJob(lambda: check(place, tomorrow=tomorrow))
        self._store_job("_weather_job", job)
        job.ready.connect(self._weather_ready)
        job.start()

    def _weather_ready(self, speech, problem: str) -> None:
        said = problem or str(speech or "")
        self.window.home.set_reply("weather", said, "From Open-Meteo. Only the town name was sent.")
        self._note_local("weather", said)
        self._speak(said)

    # ---------- Home Assistant and music (phase 6) ----------
    def _home_ready(self) -> bool:
        from babysitter.home import HomeTokenVault

        return bool(self.controller.settings.home_url) and HomeTokenVault().has_token()

    def _maybe_house(self, text: str) -> bool:
        """A switch or music command, said by you. It is planned here and done only after your yes."""
        from babysitter.home import HomeTokenVault, list_entities, parse_house, plan

        if parse_house(text) is None:
            return False
        if not self._home_ready():
            return False  # no house set up: the words go to the model as an ordinary question
        base = self.controller.settings.home_url
        music = self.controller.settings.home_music_entity
        token = HomeTokenVault().load()
        self.window.home.set_reply(text, "Looking in Home Assistant…", "Only your own network. Nothing changes until you say yes.")
        job = _CallJob(lambda: plan(text, list_entities(base, token), music))
        self._store_job("_home_plan_job", job)
        job.ready.connect(lambda command, problem, asked=text: self._house_planned(asked, command, problem))
        job.start()
        return True

    def _house_planned(self, text: str, command, problem: str) -> None:
        from babysitter.intents import ToolIntent

        if problem or command is None:
            speech = problem or "I couldn't find that in Home Assistant. Nothing was changed."
            self.window.home.set_reply(text, speech, "")
            self._speak(speech)
            return
        self._house_command = command
        self._offer_tool(ToolIntent("home", "", command.entity_id, command.ask))

    def _run_house(self) -> None:
        from babysitter.home import HomeTokenVault, run

        command = getattr(self, "_house_command", None)
        self._house_command = None
        if command is None:
            return
        base = self.controller.settings.home_url
        token = HomeTokenVault().load()
        job = _CallJob(lambda: run(command, base, token))
        self._store_job("_home_run_job", job)
        job.ready.connect(lambda speech, problem: self._house_done(speech, problem))
        job.start()

    def _house_done(self, speech, problem: str) -> None:
        said = problem or str(speech or "Done.")
        self.window.home.set_reply("home", said, "Home Assistant, on your own network.")
        self._note_local("home", said)
        self._speak(said)

    def _save_home_clicked(self) -> None:
        page = self.window.settings_page
        self._save_home(page.home_url.text(), page.home_token.text())
        page.home_token.clear()  # the token is never left in the box

    def _save_home(self, address: str, token: str) -> str:
        from babysitter.home import HomeError, HomeTokenVault, clean_base_url

        try:
            base = clean_base_url(address)
            if token.strip():
                HomeTokenVault().save(token)
        except HomeError as exc:
            message = str(exc)
        else:
            self.controller.settings.home_url = base
            save_settings(self.controller.settings)
            message = f"Saved. BabySitter talks to {base} only, and asks before every switch."
        self.window.settings_page.home_status.setText(message)
        return message

    def _save_town(self, place: str) -> str:
        from babysitter.weather import WeatherError, clean_place

        try:
            cleaned = clean_place(place).title() if place.strip() else ""
        except WeatherError as exc:
            message = str(exc)
        else:
            self.controller.settings.weather_place = cleaned
            save_settings(self.controller.settings)
            message = f"Weather town: {cleaned}." if cleaned else "Weather town cleared."
        self.window.settings_page.home_status.setText(message)
        return message

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

    def _fill_microphones(self) -> None:
        """List the microphones. Only their names are read; nothing is opened."""
        from babysitter.microphones import default_name, list_microphones

        try:
            names, default = list_microphones(), default_name()
        except Exception:
            # No voice library on this PC yet. The list holds the default only.
            names, default = [], ""
        self.window.settings_page.set_microphones(names, self.controller.settings.microphone, default)

    def _fill_settings(self) -> None:
        page = self.window.settings_page
        toggles = page.toggles()
        for toggle in toggles:
            toggle.blockSignals(True)
        page.fill(self.controller.settings, self.controller.data_folder())
        for toggle in toggles:
            toggle.blockSignals(False)
        if not getattr(self, "_microphones_listed", False):
            # Once at start. Listing starts the sound library and asks Windows
            # for every device, so later refills keep the list; the Refresh
            # button next to it lists them again.
            self._microphones_listed = True
            self._fill_microphones()
        page.set_context(self.controller.settings.context_tokens, self.controller.settings.intelligence)
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
        # 40 ms only while the side button can be used. Otherwise a slow
        # check, so the app is not woken 25 times a second while it is off.
        wanted = 40 if allowed else 500
        timer = getattr(self, "_ptt_timer", None)
        if timer is not None and timer.interval() != wanted:
            timer.setInterval(wanted)
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
        if self._hearing_ready():
            try:
                self._recorder.start(self._mic_device())
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
        recorded = bool(getattr(self, "_recording", False))
        if recorded:
            self._recording = False
            try:
                wav = self._recorder.stop()
            except Exception:
                self._recorder.close()
                wav = b""
        from babysitter.plugins.voice.hearing import dead_silence

        if recorded and (not wav or dead_silence(wav)):
            # The microphone opened but sent nothing, or only exact silence.
            # Say which one, so a dead default is not mistaken for not being heard.
            mic = self._mic_name()
            self._show_mode(self.controller.state, "Hold to talk")
            self._pending_line = ""
            speech = f"I can't hear anything from {mic}. It's sending silence."
            self.window.home.set_reply(
                "(no sound)",
                speech,
                "Pick the microphone you talk into under Settings, Microphone. Nothing was sent.",
            )
            self._dead_mic_notice(mic)
            self._speak(speech + " Pick another one in Settings, under Microphone.")
            self._sync_keyword()
            return
        if not self._hearing_ready():
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
        self._start_hear(wav, self._heard)

    def _heard(self, text: str, audio: object = None) -> None:
        wav = bytes(audio) if isinstance(audio, (bytes, bytearray)) and audio else b""
        if wav and not getattr(self, "_skip_redecode", False):
            from babysitter.plugins.voice.hearing import model_ready as whisper_ready
            from babysitter.plugins.voice.hearing import packages_installed as whisper_installed

            if self._hearing_ready() and (self._hearing_engine() != "whisper" or (whisper_installed() and whisper_ready())):
                self._vosk_line = text
                if getattr(self, "_listener", None) is not None:
                    self._listener.stop()
                self._show_mode("thinking", "Turning speech into text on this PC.")
                self._start_hear(wav, self._merge_keyword)
                return
        self._skip_redecode = False
        if getattr(self, "_listener", None) is not None:
            self._listener.stop()
        text = (text or "").strip()
        result = getattr(getattr(self, "_hear_job", None), "result", None)
        if result is not None:
            self._hear_job.result = None
            from babysitter.plugins.voice.hearing import _matches_local

            if not result.confident and not _matches_local(text):
                self._line_unsure = True
        if not text:
            self._line_unsure = False
            self.window.home.set_reply("(nothing caught)", "I didn't catch that.", "Nothing was sent.")
            self._show_mode(self.controller.state, "Say the keyword")
            self._sync_keyword()
            return
        from babysitter.plugins.voice.keyword import strip_wake

        text = strip_wake(text, self.controller.settings.keyword) or text
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
            self._goals_open = False
            self._goal_last = ""
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
        if getattr(self, "_line_unsure", False) and match_quick_command(text) is None and match_tool(text) is None:
            self._line_unsure = False
            self.window.home.set_reply(
                text,
                "I didn't catch that clearly. Say it once more.",
                "Nothing was sent.",
            )
            self._speak("I didn't catch that clearly. Say it once more.")
            self._sync_keyword()
            return
        self._line_unsure = False
        if match_quick_command(text) is None:
            self.window.home.set_reply(text, "Sending it to the model on this PC.", "")
        self._send_heard()

    def _merge_keyword(self, whisper_text: str) -> None:
        from babysitter.plugins.voice.hearing import Transcript, merge_lines

        whisper = getattr(getattr(self, "_hear_job", None), "result", None)
        if whisper is None:
            whisper = Transcript(whisper_text or "", False)
        merged = merge_lines(getattr(self, "_vosk_line", ""), whisper)
        if getattr(self, "_hear_job", None) is not None:
            self._hear_job.result = merged
        self._skip_redecode = True
        self._heard(merged.text)

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
        self._store_job("_keyword_job", job)
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
        # Importing Vosk asks Windows for its folder. Skip that unless keyword listening is on.
        if busy or not settings.keyword_listening or self.controller.state != "on":
            self._listener.stop()
            return
        ready = keyword_packages_installed() and keyword_model_ready()
        if ready:
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
        if status == "restart":
            self._sync_keyword()
            return
        if status == "microphone":
            self.controller.settings.keyword_listening = False
            save_settings(self.controller.settings)
            self._show_keyword()
            self.window.home.set_phase(
                "on",
                f"No sound came from {self._mic_name()}. Keyword listening is off. "
                "Pick the microphone you talk into under Settings, Microphone, then turn it on again.",
            )
            return
        if status == "silent":
            # Open, but only exact silence for several seconds: a dead microphone.
            # Listening stays on, in case it starts sending sound.
            mic = self._mic_name()
            self._dead_mic_notice(mic)
            self.window.home.set_phase("on", f"No sound is coming from {mic}. Pick another under Settings, Microphone.")
            return
        if status == "talk_over":
            self._cut_off()
            self.window.home.set_phase("on", "Stopped. I heard you over the voice.")
            self._sync_keyword()
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
        self._send_heard()

    def _send_heard(self) -> None:
        text = getattr(self, "_pending_line", "").strip()
        if not text:
            self.window.home.set_reply("nothing", "Type a line first.", "Nothing was sent.")
            return
        skip_quick, self._skip_quick_once = getattr(self, "_skip_quick_once", False), False
        if not skip_quick and self._run_quick(text):
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
        mode = self.controller.reply_mode()
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
        alive = self._reply_keep_alive()
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
            context_note=self._desk_context_note(),
            note_more=lambda prompt=text, ctx=mode.num_ctx: self._writing_note(prompt, ctx),
        )
        job.turn = self._turn_id
        self._store_job("_ask_job", job)
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

    def _writing_note(self, prompt: str, num_ctx: int) -> str:
        """Plain text of the Google Doc in front, for this question only."""
        if not self.controller.settings.google_enabled:
            return ""
        from babysitter.games import foreground_window_title
        from babysitter.writing import draft_wanted, read_open_draft, writing_miss

        try:
            title = foreground_window_title()
        except Exception:
            title = ""
        # Decide first, before any token or request: a question that does
        # not need the paper never reaches Google at all.
        if not draft_wanted(prompt, title):
            return ""
        tokens: list[str] = []
        for vault in (self.google_vault, self.google_school_vault):
            try:
                token = self._token_for_google(vault) or ""
            except (GoogleError, SecretsError):
                continue
            if token:
                tokens.append(token)
        if not tokens:
            return writing_miss(prompt)
        limit = 1600 if num_ctx <= 4096 else 7000 if num_ctx >= 16000 else 4000
        try:
            draft = read_open_draft(tokens, title, limit=limit)
        except Exception:
            return writing_miss(prompt)
        if draft is None:
            return writing_miss(prompt)
        return draft.note

    def _read_draft(self) -> None:
        if not self.controller.settings.google_enabled:
            self._show_google(
                "Google is off. Turn it on under Tools, then open the Google Doc. Nothing was read.",
                speak=True,
            )
            return
        running = getattr(self, "_draft_job", None)
        if running is not None and running.isRunning():
            self.window.home.set_reply("draft", "I'm already reading the Google Doc.", "Nothing else was sent.")
            return
        from babysitter.games import foreground_window_title

        # The tokens are fetched by the job, so a sign-in refresh never freezes the window.
        tokens = [account.token for account in self._linked_accounts()]
        if not tokens:
            self._show_google(
                "Sign in with Google on Tools first. Nothing was read.",
                speak=True,
            )
            return
        try:
            title = foreground_window_title()
        except Exception:
            title = ""
        self.window.home.set_reply("draft", "Reading the Google Doc you are writing.", "Plain text only. The file stays in Drive.")
        job = _DraftJob(tokens, title)
        self._store_job("_draft_job", job)
        job.ready.connect(self._draft_ready)
        job.start()

    def _draft_ready(self, speech: str, note: str) -> None:
        self.window.home.set_reply("draft", speech, "Read from Google Drive. The file was not downloaded.")
        self._note_local("draft", speech)
        if note and note != speech:
            self.window.tools_page.show_google(speech)
        self._speak(speech)

    def _desk_context_note(self) -> str:
        """Short desk state so conversational replies know about an open task or next reminder."""
        bits: list[str] = []
        try:
            record = load_day(date.today())
            for task in reversed(record.get("tasks") or []):
                if isinstance(task, dict) and not task.get("end"):
                    name = " ".join(str(task.get("name") or "").split())
                    if name:
                        bits.append(f"Open journal task: {name}.")
                    break
        except Exception:
            pass
        try:
            from babysitter.deskstore import next_reminder_line

            nxt = next_reminder_line(load_list("schedule.json"))
            if nxt and not nxt.startswith("There isn't"):
                bits.append(nxt)
        except Exception:
            pass
        return " ".join(bits)[:240]

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
        prefs = self._voice_prefs()
        if prefs.get("engine") != "kokoro":
            return  # a Kokoro clip in front of the Windows voice would be two voices
        clip = library(prefs.get("name", "")).clip(index)
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
        if take_turn(self._thread_busy(getattr(self, "_filler_job", None))) == "wait":
            self._retain_thread(self._filler_job)
            return
        self._store_job("_filler_job", job)
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
        if int(self.controller.settings.proactivity) < 3:
            # "Want another one?" at the end of every reply is the most robotic habit
            # a small model has. Proactivity 3 and up keeps the offers.
            from babysitter.plugins.voice.speech import trim_closing_offer

            reply = trim_closing_offer(reply)
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

    def _fresh_start(self) -> None:
        """Forget this conversation's context. Pins, memory, and history files stay."""
        self._history = []
        self._full_reply = ""
        self._more_text = ""
        self._awaiting_more = False
        self._session_id = ""  # what comes next is its own conversation in History
        self.window.home.set_reply("fresh start", "Fresh start. What's next?", "Pins and memory stay. The conversation so far is not sent with the next question.")
        self.controller._remember("Fresh start. The conversation context was cleared.")
        self.window.home.set_history(self.controller.history)

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
        from babysitter.deskstore import pin_kind

        kind = pin_kind({"body": body or title})
        add_item(
            "pins.json", title=title or body[:80], body=body or title, kind=kind,
            pinned=datetime.now().isoformat(timespec="minutes"),
        )
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
        add_item("pins.json", title=title, body=body, kind="reply", pinned=datetime.now().isoformat(timespec="minutes"))
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
        if text.startswith("CONFIRM goal:"):
            body = text.split(":", 1)[1].strip()
            self.window.schedule_page.goal_text.clear()
            self._apply_goal(QuickCommand("goal_add", detail=body), body)
            return
        if text.startswith("GOAL done:") or text.startswith("GOAL drop:"):
            item_id = text.split(":", 1)[1].strip()
            kind = "goal_done" if text.startswith("GOAL done:") else "goal_drop"
            self._apply_goal_id(kind, item_id, text)
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
        if text.startswith("REMOVE model:"):
            self._remove_model(text.split(":", 1)[1].strip())
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
        if text.startswith("BENCHMARK "):
            self._benchmark(text.split(" ", 1)[1].strip())
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
        if self._reply_busy():
            # Never unload in the middle of an answer. Look again shortly.
            self._game_return_timer.start(15_000)
            return
        self._return_to_game = False
        if self.controller.state == "on":
            self.controller.enter_game()

    def _look_at_screen(self, full: bool = False) -> None:
        mode = self.controller.reply_mode()
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
        alive = self._reply_keep_alive()
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
        self._store_job("_ask_job", job)
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
        running = getattr(self, "_health_job", None)
        if running is not None and running.isRunning():
            return
        self.window.health_page.body.setPlainText("Checking this PC. This can take a few seconds…")
        job = _HealthJob()
        self._store_job("_health_job", job)
        job.finished_text.connect(self.window.health_page.body.setPlainText)
        job.start()

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

    def _remove_model(self, name: str) -> None:
        cleaned = (name or "").strip()
        if not cleaned:
            self.window.models_page.body.setPlainText("Type a model name first. Nothing was removed.")
            return
        if not ask_yes_no(
            self.window,
            "Remove this model?",
            f"Ask Ollama on this PC to delete {cleaned}?\n\n"
            "You would need to download it again if you want that level later.",
            "Remove model",
            "Keep it",
        ):
            self.window.models_page.body.setPlainText("Kept the model. Nothing was removed.")
            return
        try:
            self.controller.ollama.delete_model(cleaned)
        except OllamaError as exc:
            self.window.models_page.body.setPlainText(str(exc))
            return
        self.window.models_page.remove_name.clear()
        try:
            remaining = self.controller.ollama.installed_models()
            tail = "\n".join(remaining) if remaining else "No models remain installed."
        except OllamaError:
            tail = ""
        summary = f"Removed {cleaned} from Ollama on this PC."
        self.window.models_page.body.setPlainText(f"{summary}\n\n{tail}".strip())
        self.controller._remember(summary)
        self.window.home.set_history(self.controller.history)

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
        if name.endswith("Neural"):
            name = "Heart & Sarah blend"
        raw_speed = saved.get("speed")
        try:
            speed = int(raw_speed) if raw_speed is not None else 105
        except (TypeError, ValueError):
            speed = 105
        raw_pitch = saved.get("pitch")
        try:
            pitch = int(raw_pitch) if raw_pitch is not None else -1
        except (TypeError, ValueError):
            pitch = -1
        from babysitter.plugins.voice.engines import EXTRA_VOICES, voice_ready

        if name in EXTRA_VOICES:
            if voice_ready(name):
                return {"engine": "extra", "name": name, "speed": speed, "pitch": pitch, "label": name}
            # The model file is missing, so the Windows voice speaks instead.
            return {
                "engine": "windows",
                "name": "",
                "windows_voice": "",
                "speed": speed,
                "pitch": pitch,
                "rate": sapi_rate(speed),
                "label": f"the Windows voice, until {name} is downloaded",
            }
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
            "label": _voice_label(name),
        }

    def _speak(
        self, text: str, filler: bool = False, hold_open: bool = False, alert: bool = False, windows_only: bool = False
    ) -> None:
        self._is_filler = filler
        self._alert_speech = bool(alert)
        if (text or "").strip() and not filler:
            self._said = text.strip()
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
        prefs = self._off_time_voice(self._voice_prefs())
        if alert and (windows_only or prefs.get("engine") != "kokoro" or not kokoro_ready()):
            from babysitter.plugins.voice.windows_voice import available as windows_voice_available

            if windows_only and prefs.get("engine") != "windows":
                prefs = {"engine": "kokoro", "speed": prefs.get("speed")}  # becomes the Windows voice below
            prefs = alert_voice(
                prefs,
                kokoro_ready=kokoro_ready() and not windows_only,
                windows_ok=windows_voice_available(),
            )
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

    def _off_time_voice(self, prefs: dict) -> dict:
        """The natural voices run on the graphics card. While the AI is off or a
        game has the card, a local reply (the time, the weather, the briefing) is
        said with Heart and Sarah on the processor instead, or the Windows voice,
        so the card is never taken for one sentence."""
        if self.controller.state == "on" or prefs.get("engine") != "extra":
            return prefs
        from babysitter.plugins.voice.engines import is_natural
        from babysitter.plugins.voice.kokoro_voice import DEFAULT_VOICE
        from babysitter.plugins.voice.windows_voice import available as windows_voice_available

        if not is_natural(str(prefs.get("name") or "")):
            return prefs
        kokoro = {
            "engine": "kokoro",
            "name": DEFAULT_VOICE,
            "speed": prefs.get("speed"),
            "pitch": prefs.get("pitch"),
            "label": _voice_label(DEFAULT_VOICE),
        }
        return alert_voice(kokoro, kokoro_ready=kokoro_ready(), windows_ok=windows_voice_available()) or kokoro

    def _release_idle_voices(self) -> None:
        """With the AI off or in game mode, nothing stays loaded after a sentence is said."""
        if self.controller.state not in {"off", "game"}:
            return
        release_kokoro()
        try:
            from babysitter.plugins.voice.engines import release as release_engines

            release_engines()
        except Exception:  # noqa: BLE001
            pass

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
        self._store_job("_kokoro_job", job)
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

    def _thread_busy(self, job) -> bool:
        try:
            return job is not None and job.isRunning()
        except RuntimeError:
            return False

    def _retain_thread(self, job) -> None:
        held = getattr(self, "_live_threads", None)
        if held is None:
            held = []
            self._live_threads = held
        retain_until_finished(job, held)

    def _store_job(self, name: str, job) -> None:
        previous = getattr(self, name, None)
        if previous is not None and previous is not job and self._thread_busy(previous):
            self._retain_thread(previous)
        setattr(self, name, job)
        self._retain_thread(job)

    def _start_hear(self, wav: bytes, on_heard) -> None:
        """One transcription at a time. A second clip waits, and only the newest is kept."""
        running = getattr(self, "_hear_job", None)
        if take_turn(self._thread_busy(running)) == "wait":
            self._retain_thread(running)
            self._queued_hear = (wav, on_heard)
            return
        job = _HearJob(wav, self._hearing_engine())
        self._hear_job = job
        self._retain_thread(job)
        job.heard.connect(on_heard)
        job.failed.connect(self._hear_failed)
        job.finished.connect(self._hear_finished)
        job.start()

    def _hear_finished(self) -> None:
        queued = getattr(self, "_queued_hear", None)
        self._queued_hear = None
        if not queued:
            return
        wav, on_heard = queued
        self._start_hear(wav, on_heard)

    def _start_speech(self, text: str, prefs: dict, hold_open: bool = False) -> None:
        if not text:
            self._speaking = False
            if not getattr(self, "_is_filler", False):
                self._end_model_turn()
                self._release_waiting_scan()
            self._sync_keyword()
            return
        job = _SpeakJob(text, prefs, self._turn_id)
        if take_turn(self._thread_busy(getattr(self, "_speak_job", None))) == "wait":
            self._retain_thread(self._speak_job)
            self._queued_speech = (text, prefs, hold_open)
            self._speak_job.close_input()
            stop_kokoro()
            speaker.stop()
            return
        self._speak_job = job
        self._retain_thread(job)
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
        queued = getattr(self, "_queued_speech", None)
        self._queued_speech = None
        if queued:
            text, prefs, hold_open = queued
            self._start_speech(text, prefs, hold_open=hold_open)
            return
        self._speaking = False
        self._release_idle_voices()
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
        trim_history(self._history)
        self._logged_turn = True
        if not self.controller.settings.save_conversations:
            return  # kept in memory for follow-ups only; nothing written to History
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
        ready = listening and keyword_packages_installed() and keyword_model_ready()
        heard = ready and getattr(self, "_listener", None) is not None
        goals = getattr(self, "_goals_open", False)
        # The goal talk ends when this clock runs out, even with the keyword off.
        # Otherwise "the second" would still change a goal much later.
        self._goal_clock_only = bool(goals) and not heard
        if goals or heard:
            self._followup_left = max(5, min(20, int(settings.followup_seconds)))
            self._follow_timer.start()
        if not heard:
            if goals:
                self._show_mode(self.controller.state, "Goals are on the Reminders page")
            else:
                self._show_mode(self.controller.state, "Say the keyword")
            self._sync_keyword()
            return
        self._listener.expect_followup(True)
        self._sync_keyword()
        self._show_followup()

    def _follow_tick(self) -> None:
        self._followup_left -= 1
        if self._followup_left <= 0:
            self._close_followup()
            return
        if getattr(self, "_goal_clock_only", False):
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
        # A new line arrives while the window is still open. That line can
        # still be about the goal. The window expiring is what ends the talk.
        still_open = self._followup_left > 0
        self._follow_timer.stop()
        self._followup_left = 0
        self._goal_clock_only = False
        if not still_open:
            self._goals_open = False
        if getattr(self, "_listener", None) is not None:
            self._listener.expect_followup(False)
        self._show_mode(self.controller.state, "Say the keyword")
        self._sync_keyword()

    def _run_quick(self, text: str) -> bool:
        from babysitter.goals import goal_followup

        if getattr(self, "_goals_open", False):
            followed = goal_followup(text, load_list("goals.json"), getattr(self, "_goal_last", ""))
            if followed is not None:
                self._apply_goal(followed, text)
                return True
        quick = match_quick_command(text)
        if quick is not None and quick.kind == "undo":
            return False
        if quick is None:
            intent = match_tool(text)
            if intent is None:
                self._goals_open = False
                if self._maybe_house(text):
                    return True
                return False
            self._goals_open = False
            self._offer_tool(intent)
            return True
        if quick.kind in {"goals", "goal_add", "goal_done", "goal_drop", "goal_show"}:
            self._apply_goal(quick, text)
            return True
        if quick.kind not in {"repeat", "hush"}:
            self._goals_open = False
        if quick.kind == "cancel_timer":
            self._cancel_timer(text)
            return True
        if quick.kind in {"thanks", "bye"}:
            # Said here, without the model: a thank-you or a goodbye needs no
            # answer from it, and with the AI off it would have loaded it.
            if quick.kind == "thanks":
                speech = self._phrases.thanks_reply()
            else:
                speech = self._phrases.bye_reply(night=quick.detail == "night")
                self._goals_open = False
                if getattr(self, "_followup_left", 0) > 0:
                    self._close_followup()
            self.window.home.set_reply(text, speech, "Said on this PC. The model was not asked.")
            self._note_local(text, speech)
            self._speak(speech)
            return True
        if quick.kind == "fresh_start":
            self._fresh_start()
            speech = self._phrases.fresh_start_reply()
            self.window.home.set_reply(text, speech, "Pins and memory stay. The conversation so far is not sent with the next question.")
            self._speak(speech)
            return True
        if quick.kind == "time":
            now = datetime.now().astimezone()
            speech = self._phrases.time_reply(now)
            self.window.home.set_reply(text, speech, "Read from this PC. The model was not asked.")
            self._note_local(text, speech)
            self._speak(speech)
            return True
        if quick.kind == "vram":
            snap = getattr(self.controller, "latest_status", None)
            gpu = getattr(snap, "gpu", None) if snap is not None else None
            if gpu is None:
                speech = self._phrases.vram_missing_reply()
                detail = "nvidia-smi did not report a card."
            else:
                speech = self._phrases.vram_reply(gpu.used_mib, gpu.total_mib)
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
        if quick.kind == "persona":
            self._save_persona(quick.detail)
            return True
        if quick.kind == "briefing":
            self._briefing(text)
            return True
        if quick.kind == "memories":
            facts = [str(item.get("text") or "").strip() for item in load_list("memory.json")]
            facts = [fact for fact in facts if fact]
            if not facts:
                speech = "Nothing saved yet. Say remember that, and the fact, and I'll keep it on this PC."
            else:
                newest = facts[-3:][::-1]
                count = len(facts)
                speech = (
                    f"I've saved {count} thing{'s' if count != 1 else ''}. The newest: " + "; ".join(newest) + "."
                    if count > 1
                    else f"Just one thing: {facts[0]}."
                )
            self.window.home.set_reply(text, speech, "\n".join(f"• {fact}" for fact in facts[::-1]) or "Saved on this PC, encrypted.")
            self._note_local("memories", speech)
            self._speak(speech)
            return True
        if quick.kind in {"help", "voice_speed", "volume", "power_off", "game_mode", "leave_game"}:
            speech, detail = self._local_control(quick)
            self.window.home.set_reply(text, speech, detail)
            self._note_local(text, speech)
            if speech:
                self._speak(speech)
            return True
        if quick.kind == "my_name":
            from babysitter.personality import persona_name

            name = persona_name()
            speech = (
                f"I'm {name}. You gave me that name, and I'll keep it until you say be yourself."
                if name
                else "I'm BabySitter. You can give me any name you like. Just say, call yourself, and the name."
            )
            self.window.home.set_reply("name", speech, "Answered on this PC.")
            self._note_local("name", speech)
            self._speak(speech)
            return True
        if quick.kind == "timer":
            self._begin_timer(quick.seconds, quick.detail)
            return True
        if quick.kind == "scan":
            self._begin_scan()
            return True
        if quick.kind == "mail":
            self._refresh_inbox("mail")
            return True
        if quick.kind == "calendar":
            self._refresh_inbox("calendar")
            return True
        if quick.kind in {"drive", "school_mail", "blackboard"}:
            self._refresh_inbox(quick.kind)
            return True
        if quick.kind == "draft":
            self._read_draft()
            return True
        if quick.kind == "history":
            self._speak_saved_history(text)
            return True
        if quick.kind == "next_reminder":
            self._speak_next_reminder(text)
            return True
        if quick.kind == "cancel_reminder":
            self._cancel_next_reminder(text)
            return True
        if quick.kind == "repeat":
            self._repeat_last(text)
            return True
        if quick.kind == "hush":
            self._hush()
            return True
        if quick.kind == "pin":
            self._pin_reply()
            spoken = self.window.home.spoken.text().strip()
            if spoken:
                self._speak(spoken)
            return True
        if quick.kind in {"remember", "remind"}:
            filename = "memory.json" if quick.kind == "remember" else "schedule.json"
            noun = "that" if quick.kind == "remember" else "the reminder"
            shown = (quick.detail or text).strip()
            if quick.kind == "remind" and shown.lower().startswith("to ") and len(shown) > 3:
                shown = shown[3:].strip()
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
            self._note_local(text, speech)
            self._speak(speech)
            return True
        if quick.kind == "find":
            self._find_files(text, quick.detail)
            return True
        if quick.kind == "open_number":
            self._open_numbered(text, quick.seconds)
            return True
        if quick.kind == "summarize_number":
            self._summarize_numbered(text, quick.seconds)
            return True
        if quick.kind == "drive_text":
            self._read_drive_file(text, quick.detail)
            return True
        if quick.kind == "check_update":
            self.window.home.set_reply(text, "Checking for updates…", "Checking Origin main / GitHub Releases.")
            self._check_updates(prompt_install=False, speak_result=True)
            return True
        if quick.kind == "apply_update":
            self.window.showNormal()
            self.window.raise_()
            self.window.home.set_reply(
                text,
                "Checking for updates…",
                "Nothing is installed until you confirm.",
            )
            self._check_updates(prompt_install=True, speak_result=True)
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
        self._store_job("_find_job", job)
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
        if not matches and sounds_like_a_question(wanted):
            # "Find me a recipe for pancakes" or "find the capital of australia"
            # is a question, not a file. With nothing on disk to show, it goes
            # to the model as one, instead of "Nothing matching … in Documents".
            self._pending_line = text
            self._skip_quick_once = True
            self._send_heard()
            return
        speech, detail, best = search_reply(wanted, matches, self._search_places())
        self._found_files = matches
        self._found_at = time.time()
        if best is not None:
            outcome = open_found(best)
            if not outcome.startswith("Opened"):
                speech = outcome
        self.window.home.set_reply(text, speech, detail)
        self.window.files_page.set_results(speech, detail)
        self._note_local(text, speech)
        self._speak(speech)

    def _summarize_numbered(self, text: str, number: int) -> None:
        """Read a found Word or text file on this PC and have the model sum it up.

        NEXT_ROUND phase 4: the file becomes plain text here, with the Google Doc
        cap, and is never uploaded. The model reads it as borrowed text, so an
        instruction inside the file is not followed.
        """
        from pathlib import Path

        from babysitter.filetext import FileTextError, read_file_text

        found = self._numbered_found(text, number)
        if found is None:
            return
        try:
            body = read_file_text(Path(found.path))
        except FileTextError as exc:
            speech = str(exc)
            self.window.home.set_reply(text, speech, found.path)
            self._speak(speech)
            return
        name = Path(found.path).name
        if not body.strip():
            speech = f"{name} has no words in it that I can read."
            self.window.home.set_reply(text, speech, found.path)
            self._speak(speech)
            return
        if self.controller.state != "on":
            speech = f"I read {name}. Turn the AI on and ask again, and I'll sum it up."
            self.window.home.set_reply(text, speech, body[:1200])
            self._speak(speech)
            return
        limit = 6000 if self.controller.reply_mode().num_ctx <= 4096 else 20000
        summary = f"Sum up the file {name} in two or three plain sentences, then say the one thing worth acting on, if any."
        self._pending_line = guarded_prompt(summary, body[:limit])
        self._send_heard()

    def _read_drive_file(self, text: str, name: str) -> None:
        """NEXT_ROUND phase 4: one Drive file as plain text. It is read, never uploaded or saved."""
        if not self.controller.settings.google_enabled:
            speech = "Google is off. Turn it on and sign in on Settings, Accounts and home. Nothing was sent."
            self.window.home.set_reply(text, speech, "")
            self._speak(speech)
            return
        running = getattr(self, "_drive_job", None)
        if running is not None and running.isRunning():
            speech = "I'm still reading the last Drive file. Ask again in a moment."
            self.window.home.set_reply(text, speech, "Nothing new was sent.")
            self._speak(speech)
            return
        self.window.home.set_reply(text, f"Looking in Drive for {name}…", "Only the file's text is read. Nothing is uploaded.")
        job = _DriveTextJob(self._token_for_google, name)
        self._store_job("_drive_job", job)
        job.ready.connect(lambda found, body, problem, asked=text: self._drive_text_ready(asked, found, body, problem))
        job.start()

    def _drive_text_ready(self, text: str, name: str, body: str, problem: str) -> None:
        if problem or not body.strip():
            speech = problem or f"{name} has no words in it that I can read."
            self.window.home.set_reply(text, speech, "Nothing was changed in Drive.")
            self._speak(speech)
            return
        if self.controller.state != "on":
            speech = f"I read {name} from Drive. Turn the AI on and ask again, and I'll sum it up."
            self.window.home.set_reply(text, speech, body[:1200])
            self._speak(speech)
            return
        limit = 6000 if self.controller.reply_mode().num_ctx <= 4096 else 20000
        summary = f"Sum up the Drive file {name} in two or three plain sentences, then say the one thing worth acting on, if any."
        self._pending_line = guarded_prompt(summary, body[:limit])
        self._send_heard()

    def _numbered_found(self, text: str, number: int):
        """The numbered search result, or None after saying why not."""
        matches = getattr(self, "_found_files", None) or []
        if not matches:
            speech = "Nothing is on the list. Say find and a file name first."
            self.window.home.set_reply(text, speech, "The search looks only in your chosen folders.")
            self._speak(speech)
            return None
        if time.time() - getattr(self, "_found_at", 0.0) > 600:
            self._found_files = []
            speech = "That list is from a while ago. Say find again for a fresh one."
            self.window.home.set_reply(text, speech, "A numbered list is good for 10 minutes.")
            self._speak(speech)
            return None
        if number < 1 or number > len(matches):
            speech = f"The list goes from 1 to {len(matches)}."
            self.window.home.set_reply(text, speech, "Say a number from the list.")
            self._speak(speech)
            return None
        return matches[number - 1]

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
        self._note_local(text, speech)
        self._speak(speech)

    def _reveal_goals(self) -> None:
        """Open the window on the Reminders page, where the goals are listed."""
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
        self.window.show_page(self.window.home.pin_card)  # v3: goals are on the Board
        self.window.schedule_page.refresh_goals()

    def _apply_goal(self, quick: QuickCommand, text: str) -> None:
        from babysitter.goals import apply_spoken

        turn = apply_spoken(load_list("goals.json"), quick, getattr(self, "_goal_last", ""))
        save_list("goals.json", turn.items)
        self._goal_last = turn.last_id
        self._goals_open = True
        if turn.added_id:
            self._soft_undo = {
                "kind": "note",
                "until": time.time() + 10,
                "file": "goals.json",
                "id": turn.added_id,
            }
        self._reveal_goals()
        self.window.home.set_reply(text[:80] or "goals", turn.speech, turn.detail)
        self._note_local(text, turn.speech)
        self._speak(turn.speech)

    def _apply_goal_id(self, kind: str, item_id: str, text: str) -> None:
        """A button on the Reminders page named the goal by its id."""
        from babysitter.goals import goals_detail

        items = [dict(item) for item in load_list("goals.json")]
        found = next((item for item in items if str(item.get("id") or "") == item_id), None)
        if found is None:
            self._speak("I don't see that goal.")
            return
        name = " ".join(str(found.get("text") or "Goal").split()) or "Goal"
        if kind == "goal_drop":
            items = [item for item in items if str(item.get("id") or "") != item_id]
            speech = f"Dropped {name}."
            self._goal_last = ""
        elif str(found.get("done") or "") == "yes":
            speech = f"{name} is already done."
            self._goal_last = item_id
        else:
            found["done"] = "yes"
            speech = f"{name} is done. It stays on the Reminders page."
            self._goal_last = item_id
        save_list("goals.json", items)
        self._goals_open = True
        self._reveal_goals()
        detail = goals_detail(items)
        self.window.home.set_reply(text[:80] or "goals", speech, detail)
        self._note_local(text, speech)
        self._speak(speech)

    def _briefing(self, text: str) -> None:
        """The day in a few sentences: the date, the next reminder, open goals, then
        the linked accounts if any. Weather is offered, not fetched: it still needs a yes."""
        from babysitter.deskstore import next_reminder_line

        now = datetime.now().astimezone()
        hour = now.hour
        greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 18 else "Good evening")
        parts = [f"{greeting}. It's {now.strftime('%A')}, {now.strftime('%B')} {now.day}."]
        reminder = next_reminder_line(load_list("schedule.json"))
        if reminder and not reminder.lower().startswith(("no reminder", "nothing")):
            parts.append(reminder)
        goals = [item for item in load_list("goals.json") if str(item.get("done") or "") != "yes"]
        if goals:
            first = str(goals[0].get("text") or goals[0].get("title") or "").strip()
            parts.append(
                f"You have {len(goals)} open goal{'s' if len(goals) != 1 else ''}"
                + (f", starting with {first}." if first else ".")
            )
        if self.controller.settings.weather_place:
            parts.append("Say what's the weather if you want the forecast.")
        speech = " ".join(parts)
        self.window.home.set_reply(text, speech, "Read from this PC. The linked accounts follow, if any.")
        self._note_local("briefing", speech)
        self._speak(speech)
        settings = self.controller.settings
        if settings.google_enabled or settings.microsoft_enabled:
            self._start_google("both", speak_errors=False)

    def _speak_next_reminder(self, text: str) -> None:
        from babysitter.deskstore import next_reminder_line

        speech = next_reminder_line(load_list("schedule.json"))
        self.window.home.set_reply(text, speech, "Read from this PC. Nothing was sent.")
        self._note_local(text, speech)
        self._speak(speech)

    def _cancel_next_reminder(self, text: str) -> None:
        now = datetime.now().astimezone()
        far = now + timedelta(days=3650)
        waiting: list[tuple[datetime, dict]] = []
        for item in load_list("schedule.json"):
            if str(item.get("fired") or "") == "yes":
                continue
            moment = far
            due = str(item.get("due") or "").strip()
            if due:
                try:
                    parsed = datetime.fromisoformat(due)
                except ValueError:
                    parsed = None
                if parsed is not None:
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=now.tzinfo)
                    moment = parsed
            waiting.append((moment, item))
        if not waiting:
            speech = "There isn't a reminder waiting."
            self.window.home.set_reply(text, speech, "Reminders stay on this PC.")
            self._speak(speech)
            return
        waiting.sort(key=lambda pair: pair[0])
        target = waiting[0][1]
        item_id = str(target.get("id") or "")
        remove_item("schedule.json", item_id)
        if item_id and item_id == str(getattr(self, "_active_timer_id", "")):
            timer = getattr(self, "_active_timer", None)
            if timer is not None:
                timer.stop()
            self._active_timer = None
        self.window.schedule_page.refresh()
        words = " ".join(str(target.get("text") or "Reminder").split()) or "Reminder"
        speech = "Cancelled the alarm." if words.lower() == "alarm" else f"Cancelled the reminder: {words}."
        self.window.home.set_reply(text, speech, "It was removed on this PC. Nothing was sent.")
        self._note_local(text, speech)
        self._speak(speech)

    def _repeat_last(self, text: str) -> None:
        said = str(getattr(self, "_said", "") or "").strip()
        if not said:
            speech = self._phrases.repeat_missing_reply()
            self.window.home.set_reply(text, speech, "A reply has to finish before it can be repeated.")
            self._speak(speech)
            return
        self.window.home.set_reply(text, said, "The same line, said again. Nothing was sent.")
        self._speak(said)

    def _hush(self) -> None:
        busy = getattr(self, "_speaking", False) or (
            getattr(self, "_ask_job", None) is not None and self._ask_job.isRunning()
        )
        if busy:
            self._cut_off()
            return
        speech = self._phrases.hush_reply()
        self.window.home.set_reply("quiet", speech, "Nothing was speaking.")
        self._speak(speech)

    def _begin_timer(self, seconds: int, detail: str = "") -> None:
        """A spoken timer is a reminder due that many seconds from now."""
        previous = getattr(self, "_active_timer", None)
        if previous is not None:
            previous.stop()
        moment = datetime.now().astimezone() + timedelta(seconds=seconds)
        text = " ".join((detail or "Timer").split())[:200] or "Timer"
        label = timer_label(seconds)
        speech = self._phrases.timer_saved_reply(label, text)
        item = self._save_local(
            "schedule.json",
            text,
            "the reminder",
            due=moment.isoformat(timespec="seconds"),
            speech_override=speech,
        )
        if not item:
            return
        timer = QTimer(self.window)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda item_id=item["id"], name=text: self._timer_finished(name, item_id))
        timer.start(seconds * 1000)
        self._active_timer = timer
        self._active_timer_id = item["id"]
        self._undo_until = time.time() + 10
        self.window.home.set_reply(
            "timer",
            speech,
            f"It is a reminder for {label}. It stays on this PC and rings while BabySitter is open.",
        )

    def _cancel_timer(self, text: str) -> None:
        """Stop the running timer at any point before it rings."""
        timer_id = str(getattr(self, "_active_timer_id", "") or "")
        waiting = timer_id and any(
            str(item.get("id") or "") == timer_id and str(item.get("fired") or "") != "yes"
            for item in load_list("schedule.json")
        )
        if getattr(self, "_active_timer", None) is not None and waiting:
            self._undo_until = time.time() + 1
            self._undo_timer()
            return
        speech = "There isn't a timer running."
        self.window.home.set_reply(text, speech, "Nothing was changed.")
        self._note_local(text, speech)
        self._speak(speech)

    def _undo_timer(self) -> None:
        now = time.time()
        if now <= getattr(self, "_undo_until", 0) and getattr(self, "_active_timer", None) is not None:
            self._active_timer.stop()
            self._active_timer = None
            self._undo_until = 0
            timer_id = str(getattr(self, "_active_timer_id", "") or "")
            self._active_timer_id = ""
            if timer_id:
                remove_item("schedule.json", timer_id)
                self.window.schedule_page.refresh()
                self._show_reminder_clock()
            soft = getattr(self, "_soft_undo", None)
            if soft and str(soft.get("id") or "") == timer_id:
                self._soft_undo = None
            speech = "Cancelled the timer."
            self.window.home.set_reply("undo", speech, "Nothing else was changed.")
            self._note_local("undo", speech)
            self._speak(speech)
            return
        soft = getattr(self, "_soft_undo", None)
        if soft and now <= float(soft.get("until") or 0):
            self._undo_soft(soft)
            return
        speech = self._phrases.undo_empty_reply()
        self.window.home.set_reply("undo", speech, "Nothing was changed.")
        self._speak(speech)

    def _undo_soft(self, soft: dict) -> None:
        self._soft_undo = None
        kind = soft.get("kind")
        if kind == "note":
            timer = getattr(self, "_active_timer", None)
            if timer is not None and str(soft.get("id") or "") == str(getattr(self, "_active_timer_id", "")):
                timer.stop()
                self._active_timer = None
                self._active_timer_id = ""
                self._undo_until = 0
            remove_item(str(soft.get("file") or ""), str(soft.get("id") or ""))
            self.window.schedule_page.refresh()
            self.window.memory_page.refresh()
            self._show_reminder_clock()
            speech = self._phrases.undo_note_reply()
        elif kind == "close":
            speech = "I can't reopen it. It is already closed."
        elif kind == "startup":
            try:
                self._startup_store.restore(str(soft.get("name") or ""), str(soft.get("command") or ""))
                speech = "Turned it back on at startup."
            except Exception:
                speech = "I could not put that startup item back."
        else:
            speech = self._phrases.undo_empty_reply()
        self.window.home.set_reply("undo", speech, "Nothing else was changed.")
        self._note_local("undo", speech)
        self._speak(speech)

    def _save_local(
        self,
        filename: str,
        text: str,
        noun: str,
        due: str = "",
        speech_override: str = "",
    ) -> dict:
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
        if filename.startswith("schedule") or filename.startswith("goals"):
            self.window.schedule_page.refresh()
            self._show_reminder_clock()
        else:
            self.window.memory_page.refresh()
        if speech_override:
            speech = speech_override
        elif due:
            moment = datetime.fromisoformat(due)
            speech = self._phrases.reminder_saved_reply(spoken_when(moment), text)
        elif filename.startswith("schedule"):
            speech = self._phrases.untimed_reminder_reply()
        else:
            speech = self._phrases.memory_saved_reply(text if noun == "that" else "")
        self.window.home.set_reply(text[:80], speech, "It stays on this PC. Nothing was sent.")
        self._note_local(text, speech)
        self._speak(speech)
        return item

    def _tick_reminders(self) -> None:
        # One read of the list each second, shared by both steps.
        items = load_list("schedule.json")
        self._check_reminders(items)
        self._show_reminder_clock(items)

    def _show_reminder_clock(self, items: list | None = None) -> None:
        from babysitter.deskstore import next_reminder_line

        if items is None:
            items = load_list("schedule.json")
        self.window.schedule_page.tick(items)
        line = next_reminder_line(items)
        self.window.home.set_countdown(line)
        self.window.set_next(line)

    def _check_reminders(self, items: list | None = None) -> None:
        """Say a saved reminder once its clock time has arrived."""
        if getattr(self, "_speaking", False):
            return
        now = datetime.now().astimezone()
        if items is None:
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
        from babysitter.phrasing import PhraseBook

        speech = PhraseBook.ring_line(str(pending.get("text") or ""))
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
        self._note_local(text, speech)
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
        running = getattr(self, "_scan_job", None)
        if running is not None and running.isRunning():
            return
        settings = self.controller.settings
        watched_games = list(settings.game_processes)
        snap = getattr(self.controller, "latest_status", None)
        if snap is not None and settings.detect_games and snap.detected_game:
            watched_games.append(snap.detected_game)
        self.window.home.set_reply("scan", "Checking this PC.", "Reading apps, startup items, and Windows Defender. Nothing is changed.")
        self.window.health_page.body.setPlainText("Checking this PC. This takes a few seconds…")
        job = _ScanJob(watched_games)
        self._store_job("_scan_job", job)
        job.finished_scan.connect(self._scan_ready)
        job.start()

    def _scan_ready(self, outcome) -> None:
        if isinstance(outcome, Exception):
            speech = "I couldn't read this PC just now. I did not change anything."
            self.window.health_page.body.setPlainText(speech)
            self.window.home.set_reply("scan", speech, str(outcome)[:500])
            self._speak(speech)
            return
        result, (report_said, report_detail) = outcome
        self._suggestions = list(result.suggestions)
        self._suggestion_at = 0
        self._awaiting_more = False
        parts: list[str] = [report_said]
        if result.memory_line:
            parts.append(result.memory_line)
        if result.left_games:
            parts.append("I left games alone.")
        self._scan_detail = report_detail
        self._scan_prefix = (" ".join(parts) + " ") if parts else ""
        if not self._suggestions:
            speech = self._scan_prefix.strip()
            self._scan_prefix = ""
            self._arm_yes_no(False)
            self.window.health_page.body.setPlainText(f"{speech}\n\n{report_detail}")
            self.window.home.set_reply("scan", speech, report_detail)
            self._note_local("scan", speech)
            self._speak(speech)
            return
        self._speak_current_suggestion()

    def _speak_current_suggestion(self) -> None:
        item = self._suggestions[self._suggestion_at]
        speech = self._scan_prefix + item.speech
        self._scan_prefix = ""
        detail = getattr(self, "_scan_detail", "")
        self.window.health_page.body.setPlainText(
            speech + "\n\nSay yes, or say no." + (f"\n\n{detail}" if detail else "")
        )
        self.window.home.set_reply("scan", speech, "Nothing changes until you say yes.")
        self._note_local("scan", speech)
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
        self._note_local(answer, speech)
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
        self._refresh_inbox(kind or "mail")

    def _set_blackboard(self, on: bool) -> None:
        self.controller.settings.blackboard_enabled = bool(on)
        save_settings(self.controller.settings)

    def _save_blackboard(self, url: str) -> None:
        page = self.window.tools_page
        try:
            self.blackboard_vault.save(url)
        except (FeedError, SecretsError) as exc:
            page.show_google(str(exc))
            return
        self.controller.settings.blackboard_enabled = True
        save_settings(self.controller.settings)
        page.set_blackboard_enabled(True)
        page.clear_blackboard_box()
        page.show_google("The Blackboard link is saved. It is encrypted on this PC and it is not in settings.json.")
        self._refresh_inbox("blackboard")

    def _linked_accounts(self):
        """Each linked Google account, with a function that fetches its token later."""
        from babysitter.inbox import Account

        accounts = []
        if not self.controller.settings.google_enabled:
            return self._microsoft_accounts()
        for vault, name, mail, calendar, drive in (
            (self.google_vault, "Google", "Mail", "Calendar", "Drive"),
            (self.google_school_vault, "School Google", "School mail", "School calendar", "School Drive"),
        ):
            try:
                linked = vault.has_token()
            except Exception:
                linked = False
            if linked:
                accounts.append(Account(name, mail, calendar, drive, lambda v=vault: self._token_for_google(v)))
        return accounts + self._microsoft_accounts()

    # ---------- Outlook / Microsoft 365 ----------
    def _microsoft_vault(self):
        vault = getattr(self, "_ms_vault", None)
        if vault is None:
            from babysitter.plugins.tools.microsoft_account import MicrosoftVault

            vault = self._ms_vault = MicrosoftVault()
        return vault

    def _microsoft_accounts(self):
        from babysitter.inbox import Account
        from babysitter.plugins.tools.microsoft_account import outlook_index, read_outlook

        settings = self.controller.settings
        try:
            linked = settings.microsoft_enabled and self._microsoft_vault().has_token()
        except Exception:
            linked = False
        if not linked:
            return []
        return [Account("Outlook", "Outlook", "Outlook calendar", "OneDrive", self._token_for_microsoft,
                        reader=read_outlook, indexer=outlook_index)]

    def _token_for_microsoft(self) -> str | None:
        """Runs inside the background read, so a refresh never freezes the window."""
        from babysitter.plugins.tools.microsoft_account import MicrosoftError, refresh_access

        vault = self._microsoft_vault()
        bundle = vault.load_bundle()
        if not bundle:
            return None
        refresh = str(bundle.get("refresh_token") or "")
        client_id = self.controller.settings.microsoft_client_id
        if refresh and client_id and int(bundle.get("expires_at") or 0) < time.time() + 60:
            try:
                bundle = refresh_access(client_id, refresh)
            except MicrosoftError as exc:
                raise GoogleError("The Microsoft sign-in expired. Sign in again on Accounts and home.") from exc
            vault.save_bundle(bundle)
        return str(bundle.get("access_token") or "") or None

    def _microsoft_sign_in(self, client_id: str) -> None:
        from babysitter.plugins.tools.microsoft_account import authorization_url, clean_client_id, pkce_pair

        page = self.window.tools_page
        try:
            cleaned = clean_client_id(client_id)
        except SecretsError as exc:
            page.microsoft_status.setText(str(exc))
            return
        if not self._microsoft_vault().available:
            page.microsoft_status.setText("Saving the Microsoft sign-in needs Windows. Nothing was sent.")
            return
        self.controller.settings.microsoft_client_id = cleaned
        save_settings(self.controller.settings)
        verifier, challenge = pkce_pair()
        state = verifier[:16]
        job = _MicrosoftSignInJob(cleaned, verifier, state, authorization_url(cleaned, state, challenge))
        self._store_job("_ms_sign_in_job", job)
        job.open_browser.connect(lambda link: QDesktopServices.openUrl(QUrl(link)))
        job.finished_ok.connect(self._microsoft_signed_in)
        job.failed.connect(page.microsoft_status.setText)
        job.start()
        page.microsoft_status.setText("Waiting for your Microsoft account in your browser. Read-only mail, calendar, and OneDrive.")

    def _microsoft_signed_in(self) -> None:
        job = getattr(self, "_ms_sign_in_job", None)
        bundle = getattr(job, "bundle", None)
        if job is not None:
            job.bundle = None
        page = self.window.tools_page
        if not bundle:
            page.microsoft_status.setText("Microsoft sign-in did not return a token. Nothing was saved.")
            return
        try:
            self._microsoft_vault().save_bundle(bundle)
        except SecretsError as exc:
            page.microsoft_status.setText(str(exc))
            return
        self.controller.settings.microsoft_enabled = True
        save_settings(self.controller.settings)
        self._refresh_privacy()
        page.microsoft_status.setText("Signed in to Microsoft. The sign-in is encrypted on this PC. Outlook shows in Today.")
        self._refresh_inbox("mail")

    def _microsoft_sign_out(self) -> None:
        self._microsoft_vault().delete()
        self.controller.settings.microsoft_enabled = False
        save_settings(self.controller.settings)
        self._refresh_privacy()
        self.window.tools_page.microsoft_status.setText("Signed out. The Microsoft sign-in was deleted from this PC.")

    def _linked_feed(self):
        if self.controller.settings.blackboard_enabled and self.blackboard_vault.has_feed():
            return self.blackboard_vault.load
        return None

    def _refresh_inbox(self, lead: str = "all") -> None:
        page = self.window.tools_page
        running = getattr(self, "_inbox_job", None)
        if running is not None and running.isRunning():
            page.show_google("I'm already reading the linked accounts.")
            return
        accounts, feed = self._linked_accounts(), self._linked_feed()
        if not accounts and feed is None:
            page.set_inbox([
                "Nothing is linked yet. Paste the Google desktop client id, then Sign in with Google.",
            ])
            page.show_google(
                "Nothing is linked yet. The redirect to add on that client is http://127.0.0.1:8765/babysitter."
            )
            return
        page.show_google("Reading linked accounts. Mail, calendar, and Drive names only.")
        job = _LinkedJob(accounts, feed)
        self._store_job("_inbox_job", job)
        job.ready.connect(lambda inbox, lead=lead: self._inbox_ready(inbox, lead))
        job.start()

    def _inbox_ready(self, inbox, lead: str = "all") -> None:
        from babysitter.inbox import spoken

        self.window.tools_page.set_inbox(list(inbox.rows) or list(inbox.problems))
        self._notice_expired(inbox)
        self._show_google(spoken(inbox, lead=lead), speak=not self.turns.busy())

    def _notice_expired(self, inbox) -> None:
        """An expired account is one notice with one fix. The rest keep working."""
        expired = next((line for line in inbox.problems if "sign-in expired" in line), "")
        if not expired:
            return
        account = expired.split(":", 1)[0]
        self.window.show_notice(
            f"{account}: sign-in expired. Mail and calendar from that account are paused; the rest still work.",
            "Sign in again",
            lambda: self.window.show_settings_section("accounts"),
        )

    def _start_google(self, kind: str, *, speak_errors: bool, only_new: bool = False) -> bool:
        """Mail and calendar, said aloud, or only what is new since the last check.

        Every linked account counts, school Google and Blackboard too, through
        the same read as the Tools list. True when a read started.
        """
        running = getattr(self, "_google_job", None)
        if running is not None and running.isRunning():
            # The read already running keeps its own settings.
            if not only_new:
                self._show_google("I'm already checking Google.", speak=True)
            return False
        self._google_speak_errors = speak_errors
        self._google_only_new = only_new
        settings_now = self.controller.settings
        if not (settings_now.google_enabled or settings_now.microsoft_enabled or settings_now.blackboard_enabled):
            self._show_google(
                "Google mail and calendar are off. Turn them on under Tools. Nothing was sent.",
                speak=speak_errors,
            )
            return False
        accounts = self._linked_accounts()
        feed = None if only_new else self._linked_feed()
        if not accounts and feed is None:
            self._show_google(
                "Nothing is linked yet. Sign in with Google under Tools. Nothing was sent.",
                speak=speak_errors,
            )
            return False
        job = _LinkedJob(accounts, feed, want_fresh=only_new)
        self._store_job("_google_job", job)
        if only_new:
            job.ready.connect(self._linked_fresh)
        else:
            job.ready.connect(lambda inbox, kind=kind: self._linked_spoken(inbox, kind))
            self.window.tools_page.show_google("Checking the linked accounts. Only reading.")
        job.start()
        return True

    def _linked_spoken(self, inbox, kind: str) -> None:
        from babysitter.inbox import spoken

        if inbox.rows:
            self.window.tools_page.set_inbox(list(inbox.rows))
        self._notice_expired(inbox)
        only = kind if kind in {"mail", "calendar"} else ""
        self._google_ready(spoken(inbox, lead=kind, only=only) or "Nothing new on the linked accounts.")

    def _linked_fresh(self, inbox) -> None:
        speech, seen = fresh_lines(inbox.fresh_ids, inbox.fresh_titles, self._seen_google)
        if not speech and inbox.problems:
            speech = inbox.problems[0]
        self._google_poll_ready(speech, list(seen))

    def _google_ready(self, speech: str) -> None:
        failed = speech.startswith("Google did not") or speech.startswith("Google refused") or speech.startswith("Google sent")
        speak = (self._google_speak_errors or not failed) and not self.turns.busy()
        self._show_google(speech, speak=speak)

    def _show_google(self, speech: str, *, speak: bool) -> None:
        self.window.tools_page.show_google(speech)
        detail = "Nothing was sent." if "Nothing was sent" in speech else "Read only. The token stays out of the log."
        self.window.home.set_reply("google", speech, detail)
        if not getattr(self, "_google_only_new", False):
            self._note_local("google", speech)
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

    def _warn_google_week(self) -> None:
        """A day before Google's weekly sign-out, one notice a day with Sign in again."""
        from datetime import date

        from babysitter.plugins.tools.google_account import signout_warning

        today = date.today().isoformat()
        if getattr(self, "_google_week_warned", "") == today:
            return
        for label, store in (("Google", getattr(self, "google_vault", None)), ("School Google", getattr(self, "google_school_vault", None))):
            if store is None:
                continue
            try:
                warning = signout_warning(store.load_bundle(), label)
            except Exception:  # noqa: BLE001
                warning = ""
            if warning:
                self._google_week_warned = today
                self.window.show_notice(warning, "Sign in again", lambda: self.window.show_settings_section("accounts"))
                self.controller._remember(warning)
                return

    def _token_for_google(self, vault=None) -> str | None:
        store = self.google_vault if vault is None else vault
        bundle = store.load_bundle()
        if not bundle:
            return None
        refresh = str(bundle.get("refresh_token") or "")
        client_id = self.controller.settings.google_client_id
        if refresh and client_id and int(bundle.get("expires_at") or 0) < time.time() + 60:
            from babysitter.plugins.tools.google_account import ClientSecretStore

            try:
                refreshed = refresh_access(client_id, refresh, client_secret=ClientSecretStore().load())
            except GoogleError as exc:
                raise GoogleError("The Google sign-in expired. Sign in again on Tools.") from exc
            refreshed["signed_in_at"] = int(bundle.get("signed_in_at") or 0)  # a refresh is not a new sign-in
            store.save_bundle(refreshed)
            return str(refreshed.get("access_token") or "") or None
        return str(bundle.get("access_token") or "") or None

    def _set_alerts_when_off(self, on: bool) -> None:
        self.controller.settings.alerts_when_off = bool(on)
        save_settings(self.controller.settings)
        self._sync_off_alerts()

    def _off_alerts_wanted(self) -> bool:
        settings = self.controller.settings
        linked = settings.google_enabled or settings.microsoft_enabled
        return bool(settings.alerts_when_off and linked and self.controller.state in {"off", "game"})

    def _sync_off_alerts(self) -> None:
        """Run the off-time check only while it can be used: AI off or in game mode, an account linked."""
        timer = getattr(self, "_off_poll", None)
        if timer is None:
            return
        if self._off_alerts_wanted():
            if not timer.isActive():
                timer.start()
        else:
            timer.stop()

    def _check_while_off(self) -> None:
        """Phase 5. The inbox read from 1b, without the chat model. Quiet hours skip it entirely."""
        from babysitter.quiet import alerts_silenced

        if not self._off_alerts_wanted():
            self._sync_off_alerts()
            return
        settings = self.controller.settings
        if alerts_silenced(settings.quiet_hours, settings.quiet_start, settings.quiet_end):
            return
        # Marked only when this read really started, so a read you asked for is
        # never mistaken for the off-time one.
        self._off_alert_pending = bool(self._start_google("both", speak_errors=False, only_new=True))
        self._warn_google_week()

    def _google_poll_ready(self, speech: str, seen: list) -> None:
        off_alert = bool(getattr(self, "_off_alert_pending", False))
        self._off_alert_pending = False
        if speech.startswith("New from Google"):
            self._seen_google = set(seen)
            self._save_seen_google()
            if off_alert and self.controller.state != "on":
                # The AI is off: the Windows voice says it, and nothing is loaded.
                self._show_google(speech, speak=False)
                if not self.turns.busy():
                    self._speak(speech, alert=True, windows_only=True)
                return
            self._show_google(speech, speak=not self.turns.busy())
            return
        if self._google_speak_errors and speech:
            self._show_google(speech, speak=not self.turns.busy())

    def _google_sign_in(self, client_id: str, account: str = "personal") -> None:
        from babysitter.plugins.tools.google_account import clean_client_id
        from babysitter.secrets import SecretsError as _SecretsError

        page = self.window.tools_page
        try:
            cleaned = clean_client_id(client_id)
        except _SecretsError as exc:
            page.show_google(str(exc))
            return
        self.controller.settings.google_client_id = cleaned
        self.controller.settings.google_enabled = True
        save_settings(self.controller.settings)
        page.set_google_enabled(True)
        self._sign_in_account = "school" if account == "school" else "personal"
        verifier, challenge = pkce_pair()
        state = verifier[:16]
        prompt = "select_account consent" if account == "school" else "consent"
        url = authorization_url(cleaned, state, challenge, prompt=prompt)
        from babysitter.plugins.tools.google_account import ClientSecretStore

        secret = ClientSecretStore().load()
        if not secret:
            page.show_google(
                "Choose the Google client file first (Choose the Google client file… under Accounts). "
                "Google needs the client's secret to finish a sign-in. Nothing was sent."
            )
            return
        job = _SignInJob(cleaned, verifier, state, url, client_secret=secret)
        self._store_job("_sign_in_job", job)
        job.open_browser.connect(lambda link: QDesktopServices.openUrl(QUrl(link)))
        job.finished_ok.connect(self._google_signed_in)
        job.failed.connect(page.show_google)
        job.start()
        who = "the school Google account" if account == "school" else "your Google account"
        page.show_google(f"Waiting for {who} in your browser. Read-only mail, calendar, and Drive.")

    def _choose_google_client_file(self) -> None:
        """Google's client_secret_….json: the id goes in Settings, the secret is encrypted."""
        from PySide6.QtWidgets import QFileDialog

        from babysitter.plugins.tools.google_account import ClientSecretStore, client_from_file

        path, _kind = QFileDialog.getOpenFileName(
            self.window, "Choose the Google client file", str(Path.home() / "Downloads"), "Google client file (*.json)"
        )
        if not path:
            return
        page = self.window.tools_page
        try:
            client_id, secret = client_from_file(path)
            ClientSecretStore().save(secret)
        except SecretsError as exc:
            page.show_google(str(exc))
            return
        self.controller.settings.google_client_id = client_id
        self.controller.settings.google_enabled = True
        save_settings(self.controller.settings)
        page.google_client.setText(client_id)
        page.set_google_enabled(True)
        page.show_google("The Google client is saved. Its secret is encrypted on this PC. Now press Sign in with Google.")

    def _google_signed_in(self) -> None:
        job = getattr(self, "_sign_in_job", None)
        bundle = getattr(job, "bundle", None)
        if job is not None:
            job.bundle = None
        if not bundle:
            self.window.tools_page.show_google("Google sign-in did not return a token. Nothing was saved.")
            return
        store = self.google_school_vault if getattr(self, "_sign_in_account", "personal") == "school" else self.google_vault
        bundle["signed_in_at"] = int(time.time())
        try:
            store.save_bundle(bundle)
        except SecretsError as exc:
            self.window.tools_page.show_google(str(exc))
            return
        self.controller.settings.google_enabled = True
        save_settings(self.controller.settings)
        self.window.tools_page.set_google_enabled(True)
        self.window.tools_page.set_google_saved(True, store.available)
        who = "School Google" if store is self.google_school_vault else "Google"
        self.window.tools_page.show_google(
            f"Signed in to {who}. The token is encrypted on this PC. BabySitter can refresh it."
        )
        self._refresh_inbox("school_mail" if store is self.google_school_vault else "all")

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
        from babysitter.phrasing import PhraseBook

        speech = PhraseBook.ring_line(words)
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

    def _save_persona(self, name: str) -> None:
        """A name and manner for the next session. It gives no new powers."""
        from babysitter.personality import clear_persona, save_persona

        if not name:
            clear_persona()
            speech = "Okay. I'm back to being BabySitter."
        else:
            try:
                shown = save_persona(name)
            except ValueError as exc:
                speech = str(exc)
            else:
                speech = f"{shown} it is. I'll remember that, and I'll answer to it from now on."
        # The name applies at once, not at the next start: it is saved, so it
        # also comes back every time BabySitter opens.
        if getattr(self, "_session_personality", "") or self.controller.state == "on":
            self._session_personality = session_clause()
        note = "Only how I speak changes. The tools, and every confirm, stay the same."
        self.window.voice_page.status.setText(speech)
        self.window.home.set_reply("persona", speech, note)
        self._note_local("persona", speech)
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
        self._note_local("weekly review", speech)
        self._speak(speech)

    def _benchmark(self, model: str = "") -> None:
        from babysitter.intelligence import BENCHMARK_ONLY

        if model and model not in BENCHMARK_ONLY:
            return
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
        if model:
            try:
                installed = self.controller.ollama.installed_models()
            except OllamaError as exc:
                self.window.models_page.body.setPlainText(str(exc))
                return
            if not any(name == model or name.startswith(model) for name in installed):
                self.window.models_page.body.setPlainText(
                    f"{model} is not downloaded. BabySitter does not download it. "
                    f"In a terminal: ollama pull {model}. It is about twice this card's memory."
                )
                return
            # Timed with Low's context, dropped right after, then your own level loads again.
            job = _BenchJob(self.controller.ollama, model, 4096, 512, keep_alive=0)
            self._bench_reload = True
            note = f"Timing {model} three times. It spills into system memory, so this is slow. Your own model loads again afterwards."
        else:
            job = _BenchJob(self.controller.ollama, mode.model, mode.num_ctx, mode.num_batch)
            self._bench_reload = False
            note = "Timing a fixed prompt three times. Thinking is off. Words are not saved."
        self._store_job("_bench_job", job)
        self.window.models_page.body.setPlainText(note)
        job.finished_text.connect(self._benchmark_done)
        job.start()

    def _benchmark_done(self, text: str) -> None:
        if getattr(self, "_bench_reload", False):
            # A benchmark-only model was timed. It is not kept: load your own level again.
            self._bench_reload = False
            self.window.models_page.body.setPlainText(text + "\n\nTiming only. Loading your own model again.")
            self.controller.reload_model()
            return
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
        self._store_job("_install_job", job)
        self.window.voice_page.status.setText("Downloading. This can take a few minutes. You can leave this window open.")
        job.succeeded.connect(self.window.voice_page.status.setText)
        job.failed.connect(lambda message: self.window.voice_page.status.setText(message))
        job.start()

    def _refresh_pins(self) -> None:
        self.window.set_pins(load_list("pins.json"))

    def _lock_pin(self, pin_id: str, locked: bool) -> None:
        from babysitter.deskstore import update_item

        if update_item("pins.json", pin_id, locked="yes" if locked else ""):
            self._refresh_pins()

    def _restore_pin(self, pin: dict) -> None:
        from babysitter.deskstore import restore_item

        if isinstance(pin, dict) and pin.get("id"):
            restore_item("pins.json", pin)
            self._refresh_pins()
            self.controller._remember("Put the card back on the board.")
            self.window.home.set_history(self.controller.history)

    def _unpin_card(self, pin_id: str) -> None:
        if not pin_id:
            return
        pin = next((item for item in load_list("pins.json") if item.get("id") == pin_id), None)
        if pin is not None and str(pin.get("locked") or "") == "yes":
            return  # a locked card stays until it is unlocked
        remove_item("pins.json", pin_id)
        if pin is not None:
            self.window.home.show_unpinned(pin)
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
        try:
            # The extra engines and the natural-voice helper, which holds the card.
            from babysitter.plugins.voice.engines import release as release_engines

            release_engines()
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
        if self.single_instance is not None:
            self.single_instance.release()
        relaunch = self._pending_relaunch
        self._pending_relaunch = None
        if relaunch is not None:
            try:
                spawn_finish_update(
                    relaunch.manifest_path,
                    relaunch.helper_cmd,
                    relaunch.helper_env,
                )
            except Exception as exc:
                from babysitter.logsetup import get_logger

                get_logger().error("Could not start update relauncher: %s", exc)
            else:
                # A library thread that will not stop must not keep this old
                # copy alive beside the new one. Clean exit first; this is the
                # backstop if that has not happened in ten seconds.
                import os
                import threading

                backstop = threading.Timer(10.0, os._exit, args=(0,))
                backstop.daemon = True
                backstop.start()
        QApplication.quit()


def _voice_label(name: str) -> str:
    """How a Kokoro voice is named in "Speaking with …"."""
    lowered = (name or "").lower()
    if "edith" in lowered:
        return "the EDITH-style voice"
    if "blend" in lowered or "sarah" in lowered:
        return "Heart and Sarah"
    return name


def load_icon() -> QIcon:
    path = asset_path("icon.png")
    if path.is_file():
        return QIcon(str(path))
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#2dd4bf"))
    return QIcon(pixmap)


def open_folder(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))
