"""Regression tests for the full-app review: startup, commands, undo, games,
voice preferences, conversation context, performance caches, and keyboard UI.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from babysitter.controller import Controller
from babysitter.deskstore import load_list
from babysitter.games import should_hide_orb
from babysitter.ollama import STABLE_SYSTEM, chat_messages
from babysitter.settings import Settings
from babysitter.status import StatusCollector, StatusSnapshot
from babysitter.ui.shell import Shell


def _make_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    controller = Controller()
    controller.shutdown_threads()
    shell = Shell(controller)
    monkeypatch.setattr(shell, "_speak", lambda *_args, **_kwargs: None)
    return app, controller, shell


def _teardown(controller, shell):
    shell._reminder_timer.stop()
    shell._ptt_timer.stop()
    shell._follow_timer.stop()
    if getattr(shell, "_active_timer", None) is not None:
        shell._active_timer.stop()
    shell.registrar.clear()
    shell.orb.hide()
    shell.window.hide()
    controller.shutdown_threads()


def test_windows_show_path_does_not_hit_missing_qapplication(tmp_path, monkeypatch):
    _app, controller, shell = _make_shell(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shell.tray.icon, "show", lambda: None)
    monkeypatch.setattr(controller, "start", lambda: None)
    # Without QApplication imported in shell.py, Windows crashed here before opening.
    shell.show()
    _teardown(controller, shell)


def test_typed_regular_question_sends_instead_of_hanging_on_waiting(tmp_path, monkeypatch):
    _app, controller, shell = _make_shell(tmp_path, monkeypatch)
    turned_on = []
    monkeypatch.setattr(controller, "turn_on", lambda **_kw: turned_on.append(True))
    shell._on_command("who invented dancing")
    assert shell._queued_after_load == "who invented dancing"
    assert turned_on == [True]
    assert shell.window.home.spoken.text() != "Waiting."
    _teardown(controller, shell)


def test_spoken_remember_and_remind_save_clean_text_without_duplicate_prefix(tmp_path, monkeypatch):
    _app, controller, shell = _make_shell(tmp_path, monkeypatch)
    shell._run_quick("remember the cat is called Moth")
    memories = load_list("memory.json")
    assert memories[-1]["text"] == "the cat is called Moth"

    shell._run_quick("remind me at 6 pm to stretch")
    reminders = load_list("schedule.json")
    assert reminders[-1]["text"] == "stretch"
    assert reminders[-1]["due"]
    _teardown(controller, shell)


def test_undo_within_ten_seconds_cancels_timer_and_removes_due_reminder(tmp_path, monkeypatch):
    _app, controller, shell = _make_shell(tmp_path, monkeypatch)
    shell._run_quick("set a timer for 1 second to check the tea")
    assert shell._active_timer is not None
    assert len(load_list("schedule.json")) == 1

    shell._on_command("undo")
    assert shell._active_timer is None
    assert load_list("schedule.json") == []
    assert shell.window.home.spoken.text() == "Cancelled the timer."
    _teardown(controller, shell)


def test_detected_store_game_hides_orb_and_is_left_alone_by_scan(tmp_path, monkeypatch):
    assert should_hide_orb(True, "eldenring.exe", [], detected_game="eldenring.exe") is True
    assert should_hide_orb(True, "notepad.exe", [], detected_game="eldenring.exe") is False

    _app, controller, shell = _make_shell(tmp_path, monkeypatch)
    controller.settings.detect_games = True
    controller.latest_status = StatusSnapshot(
        gpu=None,
        gpu_error=None,
        cpu_percent=10.0,
        ram_used_bytes=0,
        ram_total_bytes=1,
        port_open=False,
        models=[],
        models_error=None,
        process_names=set(),
        detected_game="eldenring.exe",
    )
    captured_games = []
    import babysitter.ui.shell as shell_mod

    monkeypatch.setattr(shell_mod, "collect_startups", lambda: [])
    original_scan = shell_mod.scan

    def spy_scan(procs, startups, games=()):
        captured_games.extend(games)
        return original_scan(procs, startups, games=games)

    monkeypatch.setattr(shell_mod, "scan", spy_scan)
    import babysitter.pcreport as pcreport

    monkeypatch.setattr(pcreport, "collect_rows", lambda sample_seconds=1.0: [])
    monkeypatch.setattr(pcreport, "defender_threats", lambda run=None: [])
    shell._begin_scan()
    assert shell._scan_job.wait(5000)
    _app.processEvents()
    assert "eldenring.exe" in captured_games
    _teardown(controller, shell)


def test_voice_prefs_preserve_zero_pitch_and_guard_cloud_off_voices(tmp_path, monkeypatch):
    _app, controller, shell = _make_shell(tmp_path, monkeypatch)
    voice_path = tmp_path / "voice.json"
    voice_path.write_text(
        json.dumps({"voice": "af_heart", "speed": 100, "pitch": 0}),
        encoding="utf-8",
    )
    prefs = shell._voice_prefs()
    assert prefs["pitch"] == 0
    assert prefs["speed"] == 100
    assert prefs["name"] == "af_heart"

    shell.window.voice_page.load_saved()
    assert shell.window.voice_page.pitch[1].value() == 0
    assert shell.window.voice_page.speed[1].value() == 100

    # Selecting the Azure cloud-off option must not overwrite voice.json with an Azure ID.
    idx = shell.window.voice_page.voice.findData("en-AU-NatashaNeural")
    assert idx >= 0
    shell.window.voice_page.voice.setCurrentIndex(idx)
    shell.window.voice_page._use()
    saved_after = json.loads(voice_path.read_text(encoding="utf-8"))
    assert saved_after["voice"] == "af_heart"
    assert "stays off" in shell.window.voice_page.status.text()

    # Even if manually edited into voice.json, _voice_prefs falls back to local Kokoro.
    voice_path.write_text(json.dumps({"voice": "en-AU-NatashaNeural"}), encoding="utf-8")
    fallback = shell._voice_prefs()
    assert fallback["engine"] == "kokoro"
    assert fallback["name"] == "Heart & Sarah blend"
    _teardown(controller, shell)


def test_conversation_context_includes_local_turns_and_desk_note(tmp_path, monkeypatch):
    _app, controller, shell = _make_shell(tmp_path, monkeypatch)
    # Start a journal task and set a future reminder; desk context should summarize both.
    shell._run_quick("start task wiring the cluster")
    due = (datetime.now().astimezone() + timedelta(minutes=25)).isoformat(timespec="seconds")
    shell._save_local("schedule.json", "stretch", "the reminder", due=due)
    shell._speak_weekly()

    note = shell._desk_context_note()
    assert "wiring the cluster" in note
    assert "stretch" in note

    msgs = chat_messages(
        "what should I tackle next?",
        history=shell._history,
        facts=["Alex runs a 5-node Raspberry Pi cluster"],
        context_note=note,
    )
    assert msgs[0]["role"] == "system"
    assert "Certainly!" in STABLE_SYSTEM  # explicitly banned in system instructions
    assert "wiring the cluster" in msgs[-1]["content"]
    assert "Alex runs a 5-node Raspberry Pi cluster" in msgs[-1]["content"]
    assert any("weekly" in m["content"].lower() or "remember" in m["content"].lower() for m in msgs[1:-1])
    _teardown(controller, shell)


def test_process_scanner_caches_exe_lookup_per_live_pid(monkeypatch):
    class QuietOllama:
        def running_models(self):
            return []

    exe_calls = []

    class FakeProc:
        def __init__(self, pid: int, name: str, path: str):
            self.info = {"pid": pid, "name": name}
            self._path = path

        def exe(self):
            exe_calls.append(self.info["pid"])
            return self._path

    rows = [
        FakeProc(101, "explorer.exe", r"C:\Windows\explorer.exe"),
        FakeProc(202, "bg3.exe", r"D:\SteamLibrary\steamapps\common\Baldurs Gate 3\bin\bg3.exe"),
    ]
    import psutil

    monkeypatch.setattr(psutil, "process_iter", lambda _attrs=None: list(rows))
    collector = StatusCollector(QuietOllama())
    names1, detected1 = collector._scan_processes()
    names2, detected2 = collector._scan_processes()
    assert detected1 == "bg3.exe" and detected2 == "bg3.exe"
    assert "explorer.exe" in names1 and "bg3.exe" in names2
    # Each live PID had exe() inspected only once across the two polls.
    assert exe_calls == [101, 202]


def test_keyboard_shortcuts_focus_command_box_and_switch_pages(tmp_path, monkeypatch):
    _app, controller, shell = _make_shell(tmp_path, monkeypatch)
    win = shell.window
    win.show()

    # Ctrl+PageDown moves from Talk to the Board.
    win.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_PageDown, Qt.ControlModifier))
    assert win.show_page_key(win.current_page()) == "board"

    # Ctrl+L returns to Home and focuses the typed command box.
    win.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_L, Qt.ControlModifier))
    assert win.current_page() is win.home
    _teardown(controller, shell)
