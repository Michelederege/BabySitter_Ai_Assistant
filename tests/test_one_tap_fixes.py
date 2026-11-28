"""0.32.0: a problem comes with the one button that fixes it, and "fix it" presses it."""

from __future__ import annotations

import pytest

from babysitter.fixes import asks_for_the_fix, fix_for, section_of
from babysitter.ollama import _friendly_http
from babysitter.pictures import room_for_model
from babysitter.quiet import quiet_sentence


@pytest.mark.parametrize("message, action", [
    ("Ollama is not installed, or BabySitter cannot find ollama.exe. Install it from https://ollama.com/download", "open_ollama_page"),
    ("Ollama is listening on the whole network, not only this computer.", "restart_ollama"),
    ("Ollama did not answer at 127.0.0.1:11434. If you just installed it, restart the PC and try again.", "retry"),
    (quiet_sentence("22:00", "07:00"), "quiet_off"),
    ("Web search is off.", "settings:accounts"),
    ("Google is off. Turn it on and sign in on Settings, Accounts and home. Nothing was sent.", "settings:accounts"),
    ("Save the Home Assistant token first, under Settings, Accounts and home.", "settings:accounts"),
    ("Download speech recognition", "get_hearing"),
    ("No sound came from Headset. Keyword listening is off.", "settings:voice"),
    ("Kokoro is not downloaded yet. Download it on the Voice tab.", "settings:voice"),
    ("The sharper voice detector is on this PC. Turn it on in Settings.", "silero_on"),
])
def test_each_problem_has_its_fix(message, action):
    fix = fix_for(message)
    assert fix is not None and fix.action == action, message
    assert fix.button and fix.text


def test_a_missing_model_is_offered_by_name():
    fix = fix_for(_friendly_http(404, "model not found", "qwen3.5:9b"))
    assert fix is not None and fix.action == "pull_model:qwen3.5:9b"


def test_no_room_on_the_card_offers_low_unless_already_low():
    message = room_for_model(3000, "gemma4:12b", 8192)
    assert fix_for(message, level="medium").action == "use_low"
    assert fix_for(message, level="low").action == "retry"


@pytest.mark.parametrize("message", ["", "The AI is on. qwen3.5:9b is loaded.", "Off.", "Saved."])
def test_ordinary_messages_have_no_fix(message):
    assert fix_for(message) is None


@pytest.mark.parametrize("line, wanted", [
    ("fix it", True), ("Fix it.", True), ("yes fix it", True), ("okay, fix that", True),
    ("fix it please", True), ("fix my essay", False), ("how do I fix it myself", False), ("", False),
])
def test_fix_it_words(line, wanted):
    assert asks_for_the_fix(line) is wanted


def test_only_known_sections_open():
    assert section_of("settings:voice") == "voice"
    assert section_of("settings:nowhere") == ""
    assert section_of("retry") == ""


def _shell(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    shell = Shell(Controller())
    spoken = []
    monkeypatch.setattr(shell, "_speak", lambda text, *a, **k: spoken.append(text))
    return shell, spoken


def test_a_failed_start_shows_the_fix_and_fix_it_runs_it(tmp_path, monkeypatch):
    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        ran = []
        monkeypatch.setattr(shell, "_run_fix", lambda action: ran.append(action))
        shell._on_state("error", "Ollama did not answer at 127.0.0.1:11434. Try again.")
        assert shell.window.has_notice()
        assert shell.window.notice_action.text() == "Try again"
        assert shell._run_quick("fix it") is True
        assert ran == ["retry"] and not shell.window.has_notice()
        # Nothing showing: "fix it" goes on like any other line.
        assert shell._run_quick("fix it") is False
    finally:
        shell.window.close()


def test_quiet_hours_fix_turns_them_off_and_starts(tmp_path, monkeypatch):
    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        started = []
        monkeypatch.setattr(shell.controller, "turn_on", lambda **kw: started.append(kw))
        shell.controller.settings.quiet_hours = True
        shell._run_fix("quiet_off")
        assert shell.controller.settings.quiet_hours is False and started == [{}]
    finally:
        shell.window.close()


def test_use_low_saves_low_then_starts(tmp_path, monkeypatch):
    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        started = []
        monkeypatch.setattr(shell.controller, "turn_on", lambda **kw: started.append(kw))
        shell.controller.settings.intelligence = "medium"
        shell._run_fix("use_low")
        assert shell.controller.settings.intelligence == "low" and started == [{}]
    finally:
        shell.window.close()


def test_only_this_apps_models_are_pulled(tmp_path, monkeypatch):
    import babysitter.ui.shell as shell_module

    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        asked = []
        monkeypatch.setattr(shell_module, "ask_yes_no", lambda *a, **k: asked.append(a) or False)
        shell._run_fix("pull_model:someone-elses-model:70b")
        assert asked == []
        shell._run_fix("pull_model:qwen3.5:9b")
        assert len(asked) == 1  # it asks, and "Not now" downloads nothing
        assert getattr(shell, "_pull_job", None) is None
    finally:
        shell.window.close()
