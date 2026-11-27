"""0.31.0 audit: things that did not work together."""

from __future__ import annotations

from datetime import datetime, timedelta


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


def test_how_long_is_left_reads_the_timer_not_the_next_reminder(tmp_path, monkeypatch):
    """The help list says "how long is left"; it read the next reminder instead."""
    shell, spoken = _shell(tmp_path, monkeypatch)
    try:
        later = (datetime.now().astimezone() + timedelta(hours=3)).isoformat(timespec="seconds")
        shell._save_local("schedule.json", "call mom", "the reminder", due=later)
        shell._begin_timer(300)
        shell._run_quick("how long is left")
        assert spoken[-1].endswith("left on the timer."), spoken[-1]
        assert spoken[-1].startswith("4 minutes") or spoken[-1].startswith("5 minutes")
        shell._run_quick("what's my next reminder")
        assert not spoken[-1].endswith("left on the timer.")
    finally:
        shell.window.close()


def test_how_long_is_left_with_no_timer_still_answers(tmp_path, monkeypatch):
    shell, spoken = _shell(tmp_path, monkeypatch)
    try:
        shell._run_quick("how long is left")
        assert spoken and "left on the timer" not in spoken[-1]
    finally:
        shell.window.close()


def test_the_next_reminder_goes_with_questions_about_his_day_only(tmp_path, monkeypatch):
    """The model said "you're calling mom tomorrow" after "what is the capital of France"."""
    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        later = (datetime.now().astimezone() + timedelta(hours=3)).isoformat(timespec="seconds")
        shell._save_local("schedule.json", "call mom", "the reminder", due=later)
        assert shell._desk_context_note("what is the capital of France") == ""
        assert shell._desk_context_note("tell me a joke") == ""
        assert "call mom" in shell._desk_context_note("what should I do this evening")
    finally:
        shell.window.close()


def test_coming_up_is_a_command_not_a_chat():
    from babysitter.commands import match_quick_command

    for line in ("what have I got coming up", "anything coming up", "what's coming up", "do I have any reminders"):
        said = match_quick_command(line)
        assert said is not None and said.kind == "next_reminder", line
