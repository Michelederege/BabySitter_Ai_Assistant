"""Long run, scan B (0.29.0): commands people say that went to the model, or
were heard wrong, though only this PC can do them."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from babysitter.commands import HELP_DETAIL, match_quick_command
from babysitter.phrasing import PhraseBook


@pytest.mark.parametrize("said", ["thanks", "thank you", "ok thanks", "thanks!", "thank you."])
def test_plain_thanks_is_answered_here(said):
    quick = match_quick_command(said)
    assert quick is not None and quick.kind == "thanks"


@pytest.mark.parametrize("said, kind", [
    ("what can you do", "help"), ("help", "help"),
    ("speak slower", "voice_speed"), ("could you please talk faster", "voice_speed"),
    ("louder", "volume"), ("turn the volume up", "volume"),
    ("turn off the AI", "power_off"), ("game mode", "game_mode"), ("leave game mode", "leave_game"),
    ("cancel my alarm", "cancel_reminder"), ("when is my alarm", "next_reminder"),
    ("what's on my calendar today", "calendar"), ("what's my next meeting", "calendar"),
])
def test_local_commands(said, kind):
    quick = match_quick_command(said)
    assert quick is not None and quick.kind == kind


_ORDINARY = [
    "how do I turn off the lights in minecraft", "why do cats slow down when they get old", "what makes a car go faster",
    "can you help me with my math homework", "what happens when you go to sleep", "is game mode on the ps5 worth it",
    "how loud is a jet engine", "my alarm didn't go off this morning", "what time should I set my alarm for school",
    "thanks to the rain the game was cancelled", "how do you say thank you in japanese", "should I turn off my pc at night",
    "how do I speed up my laptop", "what can you do with leftover rice", "i need to slow down and relax",
    "turn it up by AC/DC", "the game mode setting on my tv", "come back to me later", "wake up song by arcade fire",
    "set an alarm clock on android", "remind me what photosynthesis is", "open source software", "I'm going to sleep now",
    "go to sleep you are drunk", "power off a mac", "bye bye bye nsync",
]


@pytest.mark.parametrize("sentence", _ORDINARY)
def test_ordinary_sentences_set_off_no_command(sentence):
    """Scan L: none of these may turn the AI off, change the voice, set an alarm, or open anything."""
    quick = match_quick_command(sentence)
    assert quick is None or quick.kind not in {
        "help", "voice_speed", "volume", "power_off", "game_mode", "leave_game",
        "thanks", "bye", "remind", "open_number", "cancel_reminder",
    }, (sentence, quick)


@pytest.mark.parametrize("question", ["help me write an essay", "slow down the video", "what can you do about climate change"])
def test_longer_sentences_still_reach_the_model(question):
    quick = match_quick_command(question)
    assert quick is None or quick.kind not in {"help", "voice_speed"}


def _when(said):
    quick = match_quick_command(said)
    assert quick is not None and quick.kind == "remind", said
    return quick, datetime.fromisoformat(quick.when)


def test_an_alarm_is_a_reminder_at_the_next_such_time():
    quick, moment = _when("set an alarm for 7 am")
    assert (moment.hour, moment.minute) == (7, 0) and quick.detail == "Alarm"
    quick, moment = _when("set an alarm for 6:45")
    assert moment.minute == 45
    quick, moment = _when("set an alarm for 3 pm to take my pills")
    assert moment.hour == 15 and "take my pills" in quick.detail


def test_for_five_is_a_clock_time_and_for_five_minutes_is_a_length():
    quick, moment = _when("set a reminder for 5 to call mom")
    assert moment.hour in (5, 17) and moment.minute == 0 and "call mom" in quick.detail
    _quick, moment = _when("set a reminder for 5 minutes to stretch")
    assert 0 < (moment - datetime.now().astimezone()).total_seconds() <= 5 * 60 + 2


def test_spoken_numbers_after_for_are_a_clock_time():
    """Scan P: "can you set a reminder for one forty one" was on his PC with no time."""
    _quick, moment = _when("can you set a reminder for one forty one")
    assert moment.minute == 41 and moment.hour in (1, 13)
    quick, moment = _when("set a reminder for two thirty to call mom")
    assert moment.minute == 30 and "call mom" in quick.detail
    quick, moment = _when("set an alarm for seven")
    assert moment.hour in (7, 19) and quick.detail == "Alarm"
    quick = match_quick_command("remind me for dinner")
    assert quick.kind == "remind" and quick.when == ""  # no clock in it, so none is made up


def test_reminder_sentences_read_naturally():
    book = PhraseBook()
    for _ in range(6):
        said = book.reminder_saved_reply("5:00 PM", "to call mom")
        assert "to to" not in said and "to call mom" in said
        assert "to Alarm" not in book.reminder_saved_reply("7:00 AM", "Alarm")
    assert PhraseBook.ring_line("to call mom") == "Time to call mom."
    assert PhraseBook.ring_line("Alarm") == "It's time. This is your alarm."
    assert PhraseBook.ring_line("stretch") == "Reminder: stretch."


def test_help_lists_only_real_commands():
    for example in ("set an alarm for 7 am", "what's my next reminder", "speak slower", "game mode", "brief me", "open it"):
        quick = match_quick_command(example)
        assert quick is not None, f"help promises {example!r} but it is not a command"
    assert "speak slower" in HELP_DETAIL


def _shell(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    shell = Shell(Controller())
    spoken = []
    monkeypatch.setattr(shell, "_speak", lambda text, **kw: spoken.append(text))
    return shell, spoken


def test_speak_slower_really_changes_the_voice(tmp_path, monkeypatch):
    shell, spoken = _shell(tmp_path, monkeypatch)
    try:
        (tmp_path / "voice.json").write_text(json.dumps({"voice": "Kokoro: Bella", "speed": 100}), encoding="utf-8")
        assert shell._run_quick("speak slower") is True
        saved = json.loads((tmp_path / "voice.json").read_text(encoding="utf-8"))
        assert saved == {"voice": "Kokoro: Bella", "speed": 90}
        assert shell.window.voice_page.speed[1].value() == 90
        for _ in range(5):
            shell._run_quick("speak slower")
        assert json.loads((tmp_path / "voice.json").read_text(encoding="utf-8"))["speed"] == 80
        assert "slowest" in spoken[-1]
    finally:
        shell.window.close()


def test_power_words_do_what_the_buttons_do(tmp_path, monkeypatch):
    shell, spoken = _shell(tmp_path, monkeypatch)
    try:
        calls = []
        monkeypatch.setattr(shell.controller, "turn_off", lambda **kw: calls.append("off"))
        monkeypatch.setattr(shell.controller, "enter_game", lambda **kw: calls.append("game"))
        assert shell._run_quick("turn off the AI") is True and "already off" in spoken[-1]
        monkeypatch.setattr(type(shell.controller), "state", property(lambda self: "on"))
        shell._run_quick("game mode")
        shell._run_quick("turn off the AI")
        assert calls == ["game", "off"]
        shell._run_quick("louder")
        assert "can't change the volume" in spoken[-1]
    finally:
        shell.window.close()
