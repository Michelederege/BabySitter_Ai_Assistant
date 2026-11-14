"""The scan has to survive the voice turn, not only the phrase list.

A bare "no" is not a follow-up, so the scan has to arm yes-or-no itself.
A scan asked during a reply has to run after that reply, even when the
voice never gets as far as a finished speech job.
"""

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from babysitter.pcscan import Suggestion
from babysitter.plugins.voice.keyword import _yes_or_no, command_after_keyword
from babysitter.plugins.voice.speech import followup_phrase


def _shell(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    said: list[str] = []
    shell._speak = lambda text, filler=False: said.append(text)
    shell._said = said
    shell._app = app
    return shell


def _close(shell) -> None:
    shell.registrar.clear()
    shell.controller.shutdown_threads()
    shell._app.processEvents()


def test_a_bare_no_answers_the_scan(tmp_path, monkeypatch):
    shell = _shell(tmp_path, monkeypatch)
    try:
        assert shell._listener._yes_no is False
        assert followup_phrase("no") is None
        shell._suggestions = [
            Suggestion(
                kind="close_app",
                speech="chrome.exe is using 1.8 GB. Close it?",
                name="chrome.exe",
                pid=4,
            )
        ]
        shell._suggestion_at = 0
        shell._scan_prefix = "Memory is using 20.0 of 32.0 GB, 62 percent. "
        shell._speak_current_suggestion()
        assert shell._listener._yes_no is True
        assert _yes_or_no("no") is True
        assert command_after_keyword("no", "baby sitter") is None
        shell._heard("no")
        assert shell._suggestions == []
        assert shell._listener._yes_no is False
        assert any(line.startswith("Leaving it.") for line in shell._said)
    finally:
        _close(shell)


def test_a_scan_asked_during_a_reply_runs_when_the_reply_is_over(tmp_path, monkeypatch):
    shell = _shell(tmp_path, monkeypatch)
    try:
        shell._begin_model_turn()

        class Signal:
            def __init__(self) -> None:
                self.slots: list = []

            def connect(self, slot) -> None:
                self.slots.append(slot)

        class Job:
            def __init__(self) -> None:
                self.cancel = threading.Event()
                self.running = True
                self.finished = Signal()

            def isRunning(self) -> bool:
                return self.running

        job = Job()
        shell._ask_job = job
        shell._begin_scan()
        assert shell._said == []
        assert shell._scan_when_free is True
        assert job.finished.slots == [shell._release_waiting_scan]
        assert shell._release_waiting_scan() is False

        shell._speaking = True
        job.running = False
        assert job.finished.slots[0]() is False
        assert shell._scan_when_free is True
        assert shell.turns.busy() is True

        shell._speaking = False
        shell._pending_offer = "The rest of the model answer."
        assert job.finished.slots[0]() is True
        assert shell.turns.busy() is False
        assert shell._scan_when_free is False
        assert shell._pending_offer == ""
        assert shell._said
        assert "powershell" not in shell._said[-1].lower()
        assert "rest of the model answer" not in shell._said[-1].lower()
    finally:
        _close(shell)
