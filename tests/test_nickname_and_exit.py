"""A nickname from one sentence, and no AI left running after BabySitter closes."""

import pytest

from babysitter.commands import match_quick_command
from babysitter.plugins.voice.keyword import command_after_keyword


@pytest.mark.parametrize(
    "said, name",
    [
        ("Call yourself Jarvis", "jarvis"),
        ("I'll call you Jarvis from now on", "jarvis"),
        ("I'm going to call you Friday", "friday"),
        ("From now on your name is Nova", "nova"),
        ("Your nickname is Sunny please", "sunny"),
        ("can I call you Max", "max"),
        ("let's call you Big Mo", "big mo"),
        ("change your name to Pip", "pip"),
    ],
)
def test_one_sentence_sets_the_nickname(said, name):
    quick = match_quick_command(said)
    assert quick is not None and quick.kind == "persona" and quick.detail == name


@pytest.mark.parametrize(
    "said",
    ["I'll call you back", "can I call you later", "be quiet", "call you tomorrow", "be fine"],
)
def test_ordinary_sentences_are_not_names(said):
    quick = match_quick_command(said)
    assert quick is None or quick.kind != "persona"


def test_what_is_your_name_is_answered_here():
    assert match_quick_command("What's your name?").kind == "my_name"


def test_the_nickname_is_saved_and_wakes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.personality import persona_clause, persona_name, save_persona

    save_persona("jarvis")
    assert persona_name() == "Jarvis"
    assert "Your name is Jarvis" in persona_clause()
    assert command_after_keyword("hey jarvis what time is it", "baby sitter") == "what time is it"
    assert command_after_keyword("jarvis", "baby sitter") == ""
    # Only at the start: the name in the middle of a sentence does not wake it.
    assert command_after_keyword("i told jarvis about it", "baby sitter") is None
    assert command_after_keyword("baby sitter open notes", "baby sitter") == "open notes"


def test_closing_stops_the_ollama_babysitter_started(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.controller import Controller

    controller = Controller()
    stopped: list = []
    released: list = []
    monkeypatch.setattr(controller.ollama, "stop_server", lambda: stopped.append(True))
    monkeypatch.setattr("babysitter.plugins.voice.engines.release", lambda: released.append(True))
    controller.ollama.we_started_server = True
    controller.stop_all_ai()
    assert stopped == [True] and released == [True]


def test_a_busy_quit_closes_the_tray_ollama_too(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.controller import Controller

    controller = Controller()
    calls: list = []
    controller._busy = True
    monkeypatch.setattr(controller, "turn_off", lambda **kw: calls.append(kw))
    assert controller.request_quit() == "wait"
    assert calls == [{"emergency": False, "tray_choice": "close"}]
