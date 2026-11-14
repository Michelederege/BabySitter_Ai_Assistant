"""Five simulations for every feature.

Each feature runs five different situations. A situation is one heard line,
one PC state, or one power change. Nothing here loads a model or opens a
microphone. The report prints one line per feature.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import psutil
import pytest
from PySide6.QtWidgets import QApplication

from babysitter.commands import match_quick_command, timer_label
from babysitter.intents import match_tool
from babysitter.intelligence import MODES
from babysitter.ollama import (
    IDLE_KEEP_ALIVE,
    LoadedModel,
    _terminate_psutil,
    chat_body,
    server_environment,
    spill_problem,
)
from babysitter.pcscan import scan, spoken_reading, suggestion_answer
from babysitter.plugins.tools.google_account import calendar_speech, event_lines, unread_speech
from babysitter.plugins.voice.keyword import command_after_keyword
from babysitter.plugins.voice.speech import followup_phrase, spell_codes, unread_detail, voice_and_rest
from babysitter.proactivity import weekly_review
from babysitter.quiet import in_quiet_hours, quiet_sentence
from babysitter.status import GpuInfo
from babysitter.turngate import TurnGate, run_if_idle
from babysitter.vram import LOW_CEILING_MIB, low_estimate_mib, need_mib
from tests.test_power import make, progress

GB = 1024 ** 3


@dataclass
class Outcome:
    name: str
    ok: bool
    ms: float
    spoken: str
    note: str = ""


def _timed(name: str, check) -> Outcome:
    started = time.perf_counter()
    try:
        spoken = check()
        ok, note = True, ""
    except AssertionError as exc:
        spoken, ok, note = "", False, str(exc)
    return Outcome(name, ok, (time.perf_counter() - started) * 1000, spoken, note)


def _route(text: str) -> str:
    quick = match_quick_command(text)
    if quick is not None:
        return quick.kind
    intent = match_tool(text)
    if intent is not None:
        return f"tool-{intent.kind}"
    return "model"


def _expect_route(text: str, kind: str) -> str:
    got = _route(text)
    assert got == kind, f"{text!r} went to {got}"
    return got


def _scan_speech(result) -> str:
    parts: list[str] = []
    if result.left_games:
        parts.append("I left games alone.")
    if result.memory_line:
        parts.append(result.memory_line)
    if result.summary:
        parts.append(result.summary)
    prefix = (" ".join(parts) + " ") if parts else ""
    if not result.suggestions:
        speech = prefix.strip()
        if not result.summary:
            speech = (speech + " I didn't find a heavy app or a startup item I would change.").strip()
        return speech
    return prefix + result.suggestions[0].speech


def _clock(moment: datetime) -> str:
    return moment.strftime("It's %A, %B %d, %I:%M %p.").replace(" 0", " ")


def _vram_speech(gpu: GpuInfo | None) -> str:
    if gpu is None or gpu.total_mib <= 0:
        return "I can't see the video memory from here."
    return f"Video memory is using {gpu.used_mib:,} of {gpu.total_mib:,} megabytes."


def _feature_scan() -> list[Outcome]:
    def one(name, processes, startups, games, memory, needle):
        def check():
            assert _route("baby sitter please scan my computer") == "scan"
            speech = _scan_speech(scan(processes, startups, games, memory))
            assert needle in speech, speech
            assert "powershell" not in speech.lower()
            return speech

        return _timed(name, check)

    return [
        one(
            "high memory and chrome",
            [("chrome.exe", int(1.8 * GB), 4)],
            [],
            (),
            (20 * GB, 32 * GB),
            "Memory is using 20.0 of 32.0 GB, 62 percent. chrome.exe is using 1.8 GB. Close it?",
        ),
        one(
            "quiet pc",
            [("notepad.exe", 20 * 1024 * 1024, 5)],
            [],
            (),
            (8 * GB, 32 * GB),
            "I didn't find a heavy app or a startup item I would change.",
        ),
        one(
            "a game is left alone",
            [("bg3.exe", 6 * GB, 9), ("chrome.exe", 2 * GB, 4)],
            [],
            ("bg3.exe",),
            (18 * GB, 32 * GB),
            "I left games alone.",
        ),
        one(
            "a startup item",
            [("notepad.exe", 20 * 1024 * 1024, 5)],
            [("Discord", "C:\\Discord\\Update.exe")],
            (),
            (10 * GB, 32 * GB),
            "Discord starts with Windows. Turn that off?",
        ),
        one(
            "windows itself is not closed",
            [("System", 4 * GB, 4), ("chrome.exe", int(1.2 * GB), 8)],
            [],
            (),
            (16 * GB, 32 * GB),
            "chrome.exe is using 1.2 GB. Close it?",
        ),
    ]


def _feature_health() -> list[Outcome]:
    readings = (
        ("idle", 4 * GB, 32 * GB, 3.2, "4.0 of 32.0 GB, 12 percent. CPU is at 3 percent."),
        ("busy", 20 * GB, 32 * GB, 91.4, "20.0 of 32.0 GB, 62 percent. CPU is at 91 percent."),
        ("half", 16 * GB, 32 * GB, 50, "16.0 of 32.0 GB, 50 percent. CPU is at 50 percent."),
        ("no cpu number", 9 * GB, 16 * GB, None, "9.0 of 16.0 GB, 56 percent."),
        ("no reading", 0, 0, None, "I don't have a memory reading yet."),
    )

    def one(name, used, total, cpu, needle, phrase):
        def check():
            assert _route(phrase) == "health"
            speech = spoken_reading(used, total, cpu)
            assert needle in speech, speech
            assert "I did not change anything." in speech
            return speech

        return _timed(name, check)

    phrases = (
        "how is my pc",
        "baby sitter how's my computer doing",
        "please how is the computer",
        "please how's my pc",
        "how is my computer",
    )
    # "can you pc health" strips to "pc health". Good.
    return [
        one(name, used, total, cpu, needle, phrase)
        for (name, used, total, cpu, needle), phrase in zip(readings, phrases)
    ]


def _feature_time() -> list[Outcome]:
    moments = (
        datetime(2026, 11, 14, 9, 5),
        datetime(2026, 11, 14, 0, 0),
        datetime(2026, 11, 14, 15, 30),
        datetime(2026, 11, 14, 12, 1),
        datetime(2026, 1, 2, 7, 9),
    )
    phrases = (
        "what time is it",
        "what's the time please",
        "baby sitter tell me the time",
        "please what is the time",
        "can you whats the time",
    )

    def one(moment, phrase):
        def check():
            assert _route(phrase) == "time"
            speech = _clock(moment)
            assert speech.startswith("It's ")
            assert "AM" in speech or "PM" in speech
            return speech

        return _timed(moment.strftime("%H:%M"), check)

    return [one(moment, phrase) for moment, phrase in zip(moments, phrases)]


def _feature_vram() -> list[Outcome]:
    cases = (
        ("quiet card", GpuInfo(480, 12282, 0), "480 of 12,282 megabytes"),
        ("model loaded", GpuInfo(9800, 12282, 9000), "9,800 of 12,282 megabytes"),
        ("full card", GpuInfo(12282, 12282, 11000), "12,282 of 12,282 megabytes"),
        ("small card", GpuInfo(2100, 4096, 0), "2,100 of 4,096 megabytes"),
        ("unreadable", None, "I can't see the video memory from here."),
    )
    phrases = (
        "what's my vram",
        "baby sitter video memory",
        "please how much video memory",
        "can you what is my vram",
        "vram",
    )

    def one(name, gpu, needle, phrase):
        def check():
            assert _route(phrase) == "vram"
            speech = _vram_speech(gpu)
            assert needle in speech, speech
            return speech

        return _timed(name, check)

    return [one(name, gpu, needle, phrase) for (name, gpu, needle), phrase in zip(cases, phrases)]


def _phrases(kind: str, lines: tuple[str, ...], spoken: str) -> list[Outcome]:
    def one(line):
        def check():
            assert _route(line) == kind
            return spoken

        return _timed(line, check)

    return [one(line) for line in lines]


def _feature_screen() -> list[Outcome]:
    return _phrases(
        "screen",
        (
            "look at my screen",
            "what's on my screen",
            "what is on the screen",
            "baby sitter look at the screen",
            "please what's on the screen",
        ),
        "The screen question goes to the local look, then two or three spoken sentences.",
    )


def _feature_screen_text() -> list[Outcome]:
    return _phrases(
        "screen_text",
        (
            "read the small text",
            "read the small text on my screen",
            "read the small text on the screen",
            "baby sitter please read the small text",
            "can you read the small text on my screen",
        ),
        "Small text stays a screen read. It is not sent to the model as a chat.",
    )


def _feature_mail() -> list[Outcome]:
    lists = (
        ([], 0, "No unread mail."),
        (["Package delivered"], 0, "Unread mail: Package delivered."),
        (["A", "B", "C"], 0, "Unread mail: A; B; C."),
        (["A", "B", "C", "D", "E"], 2, "2 more unread."),
        (["  ", "Board notes"], 0, "Unread mail: Board notes."),
    )
    phrases = (
        "check my email",
        "any new emails",
        "baby sitter read my email",
        "please check my mail",
        "can you check email",
    )

    def one(subjects, extra, needle, phrase):
        def check():
            assert _route(phrase) == "mail"
            speech = unread_speech(subjects, extra)
            assert needle in speech, speech
            return speech

        return _timed(phrase, check)

    return [one(*row, phrase) for row, phrase in zip(lists, phrases)]


def _feature_calendar() -> list[Outcome]:
    payloads = (
        ({"items": []}, "Nothing coming up on the calendar."),
        ({"items": [{"summary": "Dentist", "start": {"dateTime": "2026-11-14T15:00:00"}}]}, "Dentist at 2026-11-14T15:00:00"),
        (
            {"items": [
                {"summary": "One", "start": {"dateTime": "1"}},
                {"summary": "Two", "start": {"date": "2"}},
                {"summary": "Three", "start": {"dateTime": "3"}},
            ]},
            "Coming up: One at 1. Two at 2. Three at 3.",
        ),
        (
            {"items": [{"summary": f"Item {n}", "start": {"date": str(n)}} for n in range(5)]},
            "Item 2",
        ),
        ({"items": [{"summary": "All day"}]}, "Coming up: All day."),
    )
    phrases = (
        "check my calendar",
        "any meetings",
        "what's on my calendar",
        "baby sitter check calendar",
        "please what is on my calendar",
    )

    def one(payload, needle, phrase):
        def check():
            assert _route(phrase) == "calendar"
            speech = calendar_speech(event_lines(payload))
            assert needle in speech, speech
            if any(str(item.get("summary")) == "Item 4" for item in payload.get("items") or []):
                assert "Item 2" in speech
                assert "Item 3" not in speech
                assert "Item 4" not in speech
            return speech

        return _timed(phrase, check)

    return [one(*row, phrase) for row, phrase in zip(payloads, phrases)]


def _feature_remember() -> list[Outcome]:
    lines = (
        ("remember the Door code is 42", "the Door code is 42"),
        ("baby sitter remember Sam's birthday is May 2", "Sam's birthday is May 2"),
        ("please remember the wifi name is North", "the wifi name is North"),
        ("can you remember the cat is called Moth", "the cat is called Moth"),
        ("would you remember the spare key is in the tin", "the spare key is in the tin"),
    )

    def one(line, detail):
        def check():
            found = match_quick_command(line)
            assert found is not None and found.kind == "remember"
            assert found.detail == detail, found.detail
            return f"Saved. {found.detail}"

        return _timed(line, check)

    return [one(line, detail) for line, detail in lines]


def _feature_remind() -> list[Outcome]:
    lines = (
        ("remind me to call Mom", "to call Mom"),
        ("baby sitter remind me about the dentist", "about the dentist"),
        ("please remind me to water the plant", "to water the plant"),
        ("can you remind me the bins are Thursday", "the bins are Thursday"),
        ("remind me tomorrow", "tomorrow"),
    )

    def one(line, detail):
        def check():
            found = match_quick_command(line)
            assert found is not None and found.kind == "remind"
            assert found.detail == detail, found.detail
            return f"Saved. {found.detail}"

        return _timed(line, check)

    return [one(line, detail) for line, detail in lines]


def _feature_timer() -> list[Outcome]:
    cases = (
        ("set a timer for 30 seconds", 30, "30 seconds"),
        ("timer for 1 minute", 60, "1 minute"),
        ("baby sitter timer for 5 minutes please", 300, "5 minutes"),
        ("please set a timer for 1 hour", 3600, "1 hour"),
        ("can you set a timer for 90 minutes", 5400, "90 minutes"),
    )

    def one(line, seconds, label):
        def check():
            found = match_quick_command(line)
            assert found is not None and found.kind == "timer", line
            assert found.seconds == seconds
            assert timer_label(found.seconds) == label
            assert match_quick_command("timer for 0 minutes") is None
            assert match_quick_command("timer for 25 hours") is None
            return f"Timer set for {label}."

        return _timed(line, check)

    return [one(*row) for row in cases]


def _feature_undo() -> list[Outcome]:
    hits = ("undo", "cancel that", "cancel the timer", "please undo", "baby sitter cancel that")
    misses = ("undo the last email", "why is my ram so high")

    def one(line):
        def check():
            assert _route(line) == "undo"
            assert _route(misses[0]) != "undo"
            assert _route(misses[1]) == "scan"
            return "Okay."

        return _timed(line, check)

    return [one(line) for line in hits]


def _feature_why() -> list[Outcome]:
    hits = (
        "why did you say that",
        "why did you say that?",
        "baby sitter why did you say that",
        "please why did you say that",
        "can you why did you say that",
    )

    def one(line):
        def check():
            assert _route(line) == "why"
            assert _route("why is my ram so high") == "scan"
            assert _route("why is the sky blue") == "model"
            return "The last answer is read back from this PC."

        return _timed(line, check)

    return [one(line) for line in hits]


def _feature_weekly() -> list[Outcome]:
    reviews = (
        (["Door code is 42"], ["Closed Chrome"], "Saved facts: Door code is 42."),
        ([], [], "No saved facts."),
        (["One", "Two"], ["Note"], "Recent notes: Note."),
        (["A"] * 12, ["n"] * 9, "Saved facts:"),
        (["  "], ["  "], "No saved facts."),
    )
    phrases = (
        "weekly review",
        "review my week",
        "baby sitter weekly review",
        "please review my week",
        "can you weekly review",
    )

    def one(memories, notes, needle, phrase):
        def check():
            assert _route(phrase) == "weekly"
            speech = weekly_review(memories, notes)
            assert "No model was loaded" in speech
            assert needle in speech, speech
            return speech

        return _timed(phrase, check)

    return [one(*row, phrase) for row, phrase in zip(reviews, phrases)]


def _feature_rate() -> list[Outcome]:
    rows = (
        ("rate that shorter", "shorter"),
        ("too long", "shorter"),
        ("too short", "longer"),
        ("baby sitter too cold please", "warmer"),
        ("please that was just right", "just right"),
    )

    def one(line, detail):
        def check():
            found = match_quick_command(line)
            assert found is not None and found.kind == "rate"
            assert found.detail == detail
            return f"Saved. I'll use {detail} the next time the AI turns on."

        return _timed(line, check)

    return [one(*row) for row in rows]


def _feature_web() -> list[Outcome]:
    queries = (
        "ram prices",
        "how to scan my computer",
        "weather",
        "a quote with spaces",
        "KB123456",
    )

    def one(query):
        line = f"please search the web for {query}"

        def check():
            intent = match_tool(line)
            assert intent is not None and intent.kind == "web"
            assert intent.query == query
            assert "this PC" in intent.ask
            assert "About 1 credit" not in intent.ask
            return intent.ask

        return _timed(query, check)

    return [one(query) for query in queries]


def _feature_social() -> list[Outcome]:
    rows = (
        ("search tiktok for kitchen timers", "tiktok", "tiktok-posts"),
        ("search instagram for desk lamps", "instagram", "instagram-reels"),
        ("please search youtube for ram upgrades", "youtube", "youtube"),
        ("baby sitter search reddit for quiet fans", "reddit", "reddit"),
        ("can you search threads for small keyboards", "threads", "threads"),
    )

    def one(line, site, action):
        def check():
            intent = match_tool(line)
            assert intent is not None and intent.kind == "social", line
            assert intent.action_id == action
            assert site in intent.ask
            assert "About 1 credit" in intent.ask
            assert "age or gender" in intent.summary
            return intent.ask

        return _timed(site, check)

    return [one(*row) for row in rows]


def _feature_yes_no() -> list[Outcome]:
    rows = (
        ("no", "no"),
        ("yes", "yes"),
        ("leave it", "no"),
        ("no thanks", "no"),
        ("go ahead", "yes"),
    )

    def one(line, answer):
        def check():
            assert suggestion_answer(line) == answer
            assert suggestion_answer("tell me more") is None
            assert followup_phrase("no") is None
            return answer

        return _timed(line, check)

    return [one(*row) for row in rows]


def _feature_keyword() -> list[Outcome]:
    rows = (
        ("baby sitter what time is it", "what time is it"),
        ("baby sitter", ""),
        ("what time is it", None),
        ("hello baby sitter scan my computer", "scan my computer"),
        ("hey computer how is my pc", "how is my pc"),
    )

    def one(line, rest):
        def check():
            keyword = "hey computer" if line.startswith("hey") else "baby sitter"
            assert command_after_keyword(line, keyword) == rest
            return rest or "(keyword only)"

        return _timed(line, check)

    return [one(*row) for row in rows]


def _feature_speech() -> list[Outcome]:
    def numbers():
        said, rest = voice_and_rest(
            "Memory is using 20.0 of 32.0 GB. Chrome is the heavy one. I would close it. The fourth sentence stays on the screen."
        )
        assert "20.0 of 32.0 GB" in said
        assert "fourth" not in said and "fourth" in rest
        return said

    def code():
        said, _rest = voice_and_rest("The number is 20 GB.\n\n```powershell\nGet-Process\n```")
        detail = unread_detail(said, "The number is 20 GB.\n\n```powershell\nGet-Process\n```")
        assert "Get-Process" not in said
        assert "Get-Process" in detail
        return said

    def codes():
        said = spell_codes("Look up KB123456 and 0x80070005.")
        assert "K B 1 2 3 4 5 6" in said
        assert "0 x 8 0 0 7 0 0 0 5" in said
        return said

    def list_card():
        text = "Open these.\n- one\n- two\n- three\n- four"
        said, rest = voice_and_rest(text)
        assert "four" not in said
        assert rest == ""
        return said

    def empty():
        said, rest = voice_and_rest("   ")
        assert said == "" and rest == ""
        return "(nothing spoken)"

    return [
        _timed("three sentences", numbers),
        _timed("code stays on screen", code),
        _timed("error codes are spelled", codes),
        _timed("a long list is not read", list_card),
        _timed("blank reply", empty),
    ]


def _feature_quiet() -> list[Outcome]:
    rows = (
        (False, "22:00", "07:00", datetime(2026, 11, 14, 23, 0), False),
        (True, "22:00", "07:00", datetime(2026, 11, 14, 23, 0), True),
        (True, "22:00", "07:00", datetime(2026, 11, 14, 12, 0), False),
        (True, "09:00", "17:00", datetime(2026, 11, 14, 9, 0), True),
        (True, "nope", "07:00", datetime(2026, 11, 14, 23, 0), False),
    )

    def one(enabled, start, end, moment, quiet):
        def check():
            assert in_quiet_hours(enabled, start, end, moment) is quiet
            speech = quiet_sentence(start, end)
            assert start in speech and "The AI stays off." in speech
            return speech

        return _timed(moment.strftime("%H:%M") + f" quiet={quiet}", check)

    return [one(*row) for row in rows]


def _feature_turn_gate() -> list[Outcome]:
    def idle():
        gate = TurnGate()
        ran = []
        assert run_if_idle(gate, lambda: ran.append(1)) is True
        assert ran == [1]
        return "ran"

    def busy():
        gate = TurnGate()
        gate.enter()
        assert run_if_idle(gate, lambda: None) is False
        return "skipped"

    def nested():
        gate = TurnGate()
        gate.enter()
        gate.enter()
        gate.leave()
        assert gate.busy()
        return "still busy"

    def clear():
        gate = TurnGate()
        gate.enter()
        gate.leave()
        assert not gate.busy()
        return "idle"

    def floor():
        gate = TurnGate()
        gate.leave()
        assert not gate.busy()
        return "stayed idle"

    return [
        _timed("idle work runs", idle),
        _timed("a voice turn skips it", busy),
        _timed("nested turns stay busy", nested),
        _timed("the last leave opens the gate", clear),
        _timed("an extra leave does not go negative", floor),
    ]


def _feature_intelligence() -> list[Outcome]:
    def low():
        assert need_mib(MODES["low"].model, MODES["low"].num_ctx) <= LOW_CEILING_MIB
        assert low_estimate_mib() <= LOW_CEILING_MIB
        assert server_environment({}, "127.0.0.1", 11434, 4096)["OLLAMA_CONTEXT_LENGTH"] == "4096"
        return f"Low {low_estimate_mib()} MiB"

    def medium():
        assert need_mib(MODES["medium"].model, 8192) == 9500
        assert server_environment({}, "127.0.0.1", 11434, 8192)["OLLAMA_CONTEXT_LENGTH"] == "8192"
        return "Medium 9500 MiB"

    def high():
        assert need_mib(MODES["high"].model, 16384) == 11000
        assert server_environment({}, "127.0.0.1", 11434, 16384)["OLLAMA_CONTEXT_LENGTH"] == "16384"
        return "High 11000 MiB"

    def spill():
        text = spill_problem(LoadedModel("gemma4:12b", 12_000_000_000, 8_000_000_000, 8192))
        assert text and "spilled" in text
        return text

    def fitted():
        assert spill_problem(LoadedModel("qwen3.5:9b", 6_000_000_000, 5_900_000_000, 4096)) is None
        body = chat_body("qwen3.5:9b", "hello", 4096)
        assert body["keep_alive"] == IDLE_KEEP_ALIVE
        return "Low stays on the card"

    return [
        _timed("low", low),
        _timed("medium", medium),
        _timed("high", high),
        _timed("a spill is refused", spill),
        _timed("a fitted model stays", fitted),
    ]


def _feature_power() -> list[Outcome]:
    def turn(model, ctx, state):
        def check():
            service, ollama, *_rest = make()
            result = service.turn_on(
                model=model,
                num_ctx=ctx,
                cancel=threading.Event(),
                game_name=None,
                progress=progress,
            )
            assert result.state == state
            assert ollama.started_ctx == ctx
            return result.message

        return check

    def game():
        service, ollama, *_rest = make()
        service.turn_on(model="qwen3.5:9b", num_ctx=4096, cancel=threading.Event(), game_name=None, progress=progress)
        result = service.enter_game_mode(progress)
        assert result.state == "game"
        assert ollama.models == []
        assert ollama.port is True
        return result.message

    def off():
        service, ollama, *_rest = make()
        service.turn_on(model="gemma4:12b", num_ctx=8192, cancel=threading.Event(), game_name=None, progress=progress)
        result = service.turn_off(emergency=False, tray_choice="close", progress=progress)
        assert result.state == "off"
        assert ollama.models == []
        assert ollama.port is False
        return result.message

    def emergency():
        service, ollama, *_rest = make()
        ollama.tray = ["ollama app.exe"]
        service.state = "on"
        service.ollama.port = True
        result = service.turn_off(emergency=True, tray_choice="ask", progress=progress)
        assert result.state == "off"
        assert ollama.closed_tray == 1
        assert ollama.port is False
        return result.message

    return [
        _timed("turn on low", turn("qwen3.5:9b", 4096, "on")),
        _timed("turn on medium", turn("gemma4:12b", 8192, "on")),
        _timed("game mode unloads the model", game),
        _timed("off stops the server", off),
        _timed("emergency closes the tray app", emergency),
    ]


def _feature_shutdown(tmp_path, monkeypatch) -> list[Outcome]:
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    outcomes: list[Outcome] = []
    try:
        def hide():
            stopped: list[str] = []
            shell.controller.turn_off = lambda **kwargs: stopped.append(kwargs["tray_choice"])
            shell.controller.power.state = "on"
            shell._on_hidden_to_tray()
            assert stopped == ["close"]
            return "hide turns the AI off"

        def quit_resident():
            stopped: list[str] = []
            shell.controller.request_quit = lambda: "ask"
            shell.controller.quit_after_stopping = lambda: stopped.append("stop")
            shell._quit()
            assert stopped == ["stop"]
            return "quit stops Ollama"

        def quit_clear():
            calls: list[str] = []
            shell.controller.request_quit = lambda: "quit"
            shell._finish_quit = lambda: calls.append("finish")
            shell._quit()
            assert calls == ["finish"]
            return "an already off AI just closes"

        outcomes.append(_timed("hide the window", hide))
        outcomes.append(_timed("quit while the model is up", quit_resident))
        outcomes.append(_timed("quit while the AI is off", quit_clear))
    finally:
        shell.registrar.clear()
        shell.controller.shutdown_threads()
        app.processEvents()

    def keep():
        body = chat_body("gemma4:12b", "hello", 8192)
        assert body["keep_alive"] == "5m"
        assert body["keep_alive"] != -1
        return "idle model drops after 5 minutes"

    def child():
        parent = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                "import subprocess, sys, time\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                "print(child.pid, flush=True)\n"
                "time.sleep(120)\n",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert parent.stdout is not None
        child_pid = int(parent.stdout.readline().strip())
        try:
            proc = psutil.Process(child_pid)
            assert proc.ppid() == parent.pid
            _terminate_psutil(psutil.Process(parent.pid))
            assert not proc.is_running()
            return "the runner child stopped with the parent"
        finally:
            for pid in (child_pid, parent.pid):
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass

    outcomes.append(_timed("keep alive is five minutes", keep))
    outcomes.append(_timed("the runner child dies too", child))
    return outcomes


def _all(tmp_path, monkeypatch) -> list[tuple[str, list[Outcome]]]:
    return [
        ("scan", _feature_scan()),
        ("health", _feature_health()),
        ("time", _feature_time()),
        ("vram", _feature_vram()),
        ("screen", _feature_screen()),
        ("screen text", _feature_screen_text()),
        ("mail", _feature_mail()),
        ("calendar", _feature_calendar()),
        ("remember", _feature_remember()),
        ("remind", _feature_remind()),
        ("timer", _feature_timer()),
        ("undo", _feature_undo()),
        ("why", _feature_why()),
        ("weekly review", _feature_weekly()),
        ("rate", _feature_rate()),
        ("web search", _feature_web()),
        ("social search", _feature_social()),
        ("yes or no", _feature_yes_no()),
        ("keyword", _feature_keyword()),
        ("speech", _feature_speech()),
        ("quiet hours", _feature_quiet()),
        ("turn gate", _feature_turn_gate()),
        ("intelligence", _feature_intelligence()),
        ("power", _feature_power()),
        ("shutdown", _feature_shutdown(tmp_path, monkeypatch)),
    ]


def test_five_simulations_for_every_feature(tmp_path, monkeypatch, capsys):
    features = _all(tmp_path, monkeypatch)
    lines: list[str] = []
    failed = 0
    for name, outcomes in features:
        assert len(outcomes) == 5, name
        bad = [item for item in outcomes if not item.ok]
        failed += len(bad)
        slow = max(item.ms for item in outcomes)
        example = outcomes[0].spoken.replace("\n", " ")
        lines.append(f"{name}:  {5 - len(bad)}/5  slowest {slow:.2f} ms  heard: {example[:110]}")
        for item in bad:
            lines.append(f"  fail {item.name}: {item.note}")
    report = "\n".join(lines)
    print(report)
    captured = capsys.readouterr()
    assert "scan:" in captured.out
    if failed:
        pytest.fail(report)
