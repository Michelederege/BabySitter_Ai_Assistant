"""0.31.0: a request no command matched becomes a command, after one yes."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from babysitter import suggest as sg

NOW = datetime.now().astimezone()


class FakeClient:
    def __init__(self, command: str = "", fail: bool = False) -> None:
        self.command = command
        self.fail = fail
        self.calls = []

    def ask_json(self, model, system, prompt, num_ctx, schema, **kwargs):
        self.calls.append((model, prompt, num_ctx, kwargs))
        if self.fail:
            raise RuntimeError("Ollama is not running")
        return {"command": self.command}


@pytest.mark.parametrize("line", [
    "put dentist on Friday at 3",
    "I have a doctor's appointment tuesday at 10",
    "don't let me forget to take the chicken out at 5",
    "make a note that the wifi password is on the router",
    "my sister's birthday is March 4",
    "give me twenty minutes on the clock",
    "I've got soccer practice Thursday at 6",
])
def test_instructions_are_worth_a_try(line):
    assert sg.looks_like_action(line)


@pytest.mark.parametrize("line", [
    "what is photosynthesis",
    "how do I cook rice",
    "is it going to be a long winter",
    "tell me about the Roman empire",
    "",
])
def test_questions_go_straight_to_chat(line):
    assert not sg.looks_like_action(line)


def test_only_safe_kinds_are_offered():
    assert sg.accept("put dentist on friday at 3", "remind me on Friday at 3:00 pm to go to the dentist").kind == "remind"
    assert sg.accept("twenty minutes on the clock", "set a timer for 20 minutes").kind == "timer"
    assert sg.accept("note the gate code is 4412", "remember that the gate code is 4412").kind == "remember"
    assert sg.accept("add running to my goals", "add a goal to run a marathon").kind == "goal_add"
    # Opening, power, mail, scans: never, whatever the model writes.
    for command in ("open number 1", "turn off the ai", "check my email", "scan my PC", "game mode", "find my essay"):
        assert sg.accept("open my stuff please", command) is None, command
    assert sg.accept("x", "") is None
    assert sg.accept("x", "the weather is nice") is None


def test_a_reminder_must_ring_and_must_come_from_what_was_said():
    assert sg.accept("remind me to buy milk", "remind me to buy milk") is None  # no time: nothing to offer
    # The model made up the dentist: the note shares no word with what was said.
    assert sg.accept("block out 4 pm", "remind me at 4:00 pm to go to the dentist") is None
    assert sg.accept("block out 4 pm for studying", "remind me at 4:00 pm to study") is not None
    # No time was said, so the model's Friday at 9 is made up.
    assert sg.accept("schedule my haircut", "remind me on Friday at 9:00 am to get a haircut") is None


def test_waking_up_is_the_morning():
    parsed = sg.accept("wake me at half past six tomorrow", "remind me tomorrow at 6:30 pm to wake up")
    moment = datetime.fromisoformat(parsed.when)
    assert (moment.hour, moment.minute) == (6, 30)
    evening = sg.accept("wake me at 6 pm tomorrow", "remind me tomorrow at 6:00 pm to wake up")
    assert datetime.fromisoformat(evening.when).hour == 18


def test_the_question_is_built_from_the_parsed_command():
    parsed = sg.accept("put dentist on friday at 3", "remind me tomorrow at 3:00 pm to go to the dentist")
    line = sg.confirm_line(parsed, NOW)
    assert line.startswith("Set a reminder for 3:00 PM tomorrow: go to the dentist")
    assert sg.confirm_line(sg.accept("twenty minutes on the clock", "set a timer for 20 minutes")) == "Start a timer for 20 minutes?"
    assert sg.confirm_line(sg.accept("the gate code is 4412", "remember that the gate code is 4412")) == "Remember that the gate code is 4412?"


def test_any_failure_means_chat_as_before():
    assert sg.suggest(FakeClient(fail=True), "m", "put dentist on Friday at 3", 4096) is None
    assert sg.suggest(FakeClient(""), "m", "put dentist on Friday at 3", 4096) is None
    found = sg.suggest(FakeClient("remind me tomorrow at 3:00 pm to go to the dentist"), "m", "put dentist on tomorrow at 3", 4096, num_batch=256)
    assert found is not None and found[1].kind == "remind"


def test_the_same_context_size_as_the_chat_so_the_model_is_not_reloaded():
    client = FakeClient("set a timer for 5 minutes")
    sg.suggest(client, "qwen3.5:9b", "give me five minutes", 4096, num_batch=512, keep_alive="30m")
    model, _prompt, num_ctx, kwargs = client.calls[0]
    assert (model, num_ctx, kwargs["num_batch"], kwargs["keep_alive"]) == ("qwen3.5:9b", 4096, 512, "30m")


def test_ask_json_body(monkeypatch):
    from babysitter.ollama import OllamaClient

    seen = {}

    def fake_request(self, method, path, body=None, timeout=30):
        seen.update(method=method, path=path, body=body)
        return {"message": {"content": '{"command": "set a timer for 5 minutes"}'}}

    monkeypatch.setattr(OllamaClient, "_request", fake_request)
    answer = OllamaClient().ask_json("qwen3.5:9b", "sys", "give me five minutes", 4096, sg.SCHEMA, num_batch=512)
    assert answer == {"command": "set a timer for 5 minutes"}
    body = seen["body"]
    assert seen["path"] == "/api/chat" and body["stream"] is False and body["think"] is False
    assert body["format"] == sg.SCHEMA and body["options"]["temperature"] == 0
    assert body["options"]["num_ctx"] == 4096 and body["options"]["num_batch"] == 512


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


def test_yes_saves_the_reminder_and_no_leaves_it(tmp_path, monkeypatch):
    from babysitter.deskstore import load_list

    shell, spoken = _shell(tmp_path, monkeypatch)
    try:
        heard = "put dentist on Friday at 3"
        when = (NOW + timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0)
        parsed = sg.accept(heard, f"remind me on {when.strftime('%A')} at 3:00 pm to go to the dentist")
        assert parsed is not None
        shell._pending_line = heard
        shell._suggested(heard, ("remind me …", parsed))
        assert spoken[-1].startswith("Set a reminder for 3:00 PM")
        assert shell._pending_tool is not None and shell._pending_tool.kind == "command"
        assert load_list("schedule.json") == []
        shell._answer_tool("yes")
        saved = load_list("schedule.json")
        assert len(saved) == 1 and "dentist" in str(saved[0].get("text"))
        assert datetime.fromisoformat(saved[0]["due"]).hour == 15

        shell._pending_line = heard
        shell._suggested(heard, ("remind me …", parsed))
        shell._answer_tool("no")
        assert len(load_list("schedule.json")) == 1
        assert spoken[-1] == "Okay, I left it."
    finally:
        shell.window.close()


def test_no_suggestion_goes_on_to_chat(tmp_path, monkeypatch):
    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        sent = []
        monkeypatch.setattr(shell, "_send_heard", lambda: sent.append(shell._skip_quick_once))
        shell._pending_line = "make me laugh"
        shell._suggested("make me laugh", None)
        assert sent == [True]
        # A late answer for an older line is dropped.
        shell._pending_line = "something newer"
        shell._suggested("make me laugh", None)
        assert sent == [True]
    finally:
        shell.window.close()


def test_nothing_is_asked_while_the_ai_is_off(tmp_path, monkeypatch):
    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        assert shell.controller.state != "on"
        assert shell._maybe_suggest("put dentist on Friday at 3") is False
    finally:
        shell.window.close()
