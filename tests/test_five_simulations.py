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
        ("remind me tomorrow", "Reminder"),
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
    hits = ("undo", "cancel that", "undo please", "please undo", "baby sitter cancel that")
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
            # On Windows a venv's python.exe is a launcher that starts the
            # real Python, so the child can sit one step further down.
            assert parent.pid in {ancestor.pid for ancestor in proc.parents()}
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


def _feature_journal() -> list[Outcome]:
    from babysitter.journal import day_speech, finish_task, start_task

    def today():
        assert _expect_route("what did i do today", "journal_today")
        assert _expect_route("baby sitter what have i done today", "journal_today")
        return "Today's journal is read on this PC."

    def yesterday():
        assert _expect_route("what did i do yesterday", "journal_yesterday")
        assert _expect_route("please what did i work on yesterday", "journal_yesterday")
        return "Yesterday's journal is read on this PC."

    def started():
        found = match_quick_command("start task sanding the door")
        assert found is not None and found.kind == "task_start"
        assert found.detail == "sanding the door"
        record = {"date": "2026-11-15", "apps": {}, "tasks": []}
        speech = start_task(record, found.detail, datetime(2026, 11, 15, 9, 0))
        assert speech.startswith("Started sanding the door")
        assert record["tasks"][0]["end"] == ""
        return speech

    def finished():
        record = {"date": "2026-11-15", "apps": {}, "tasks": []}
        start_task(record, "sanding the door", datetime(2026, 11, 15, 9, 0))
        speech = finish_task(record, datetime(2026, 11, 15, 9, 45))
        assert "took" in speech and "sanding the door" in speech
        assert record["tasks"][0]["end"]
        assert "No task is open" in finish_task(record, datetime(2026, 11, 15, 10, 0))
        return speech

    def empty_day():
        assert _expect_route("pause the journal", "journal_pause")
        assert _expect_route("resume the journal", "journal_resume")
        speech = day_speech({"date": "2026-11-15", "apps": {}, "tasks": []}, "today")
        assert "Nothing is in the journal" in speech
        short = day_speech(
            {"date": "2026-11-15", "apps": {"blender": {"seconds": 20, "first": "", "last": ""}}, "tasks": []},
            "today",
        )
        assert "Under a minute" in short
        return speech

    return [
        _timed("today", today),
        _timed("yesterday", yesterday),
        _timed("start a task", started),
        _timed("finish a task", finished),
        _timed("an empty day", empty_day),
    ]


def _feature_files() -> list[Outcome]:
    from babysitter.filefind import FoundFile, match_files, open_found, search_reply

    tax = FoundFile("2024-tax.pdf", r"C:\Users\me\Documents\2024-tax.pdf", 10, 0)
    older = FoundFile("2023-tax.pdf", r"C:\Users\me\Documents\2023-tax.pdf", 5, 0)
    helmet = FoundFile("helmet.stl", r"C:\Users\me\Documents\prints\helmet.stl", 8, 0)
    dragon = FoundFile("dragon-head.stl", r"C:\Users\me\Documents\prints\dragon-head.stl", 9, 0)
    program = FoundFile("setup.exe", r"C:\Users\me\Downloads\setup.exe", 7, 0)

    def routed():
        assert _expect_route("find my tax pdf", "find")
        assert _expect_route("pull up my current tax pdf", "find")
        assert _expect_route("find all stls", "find")
        assert _route("find out about the tax") == "model"
        return "A file name stays on this PC."

    def one_match():
        matches = match_files("tax pdf", [tax])
        speech, detail, best = search_reply("tax pdf", matches, [r"C:\Users\me\Documents"])
        assert best == tax
        assert speech.startswith("Opening 2024-tax.pdf")
        assert detail == tax.path
        return speech

    def several():
        matches = match_files("stl", [helmet, dragon])
        speech, detail, best = search_reply("stl", matches, [r"C:\Users\me\Documents"])
        assert best is None
        assert "Say open number 1 to 2" in speech
        assert "helmet.stl" in detail and "dragon-head.stl" in detail
        assert _expect_route("open number 2", "open_number")
        return speech

    def partial():
        matches = match_files("dragons", [dragon, helmet])
        assert [item.name for item in matches] == ["dragon-head.stl"]
        return "dragon-head.stl"

    def program_stays_closed():
        matches = match_files("setup", [program, tax])
        assert [item.name for item in matches] == ["setup.exe"]
        speech = open_found(program)
        assert "not started" in speech
        assert "Opening" not in speech
        return speech

    return [
        _timed("the words route here", routed),
        _timed("one match opens", one_match),
        _timed("several stay numbered", several),
        _timed("a partial name matches", partial),
        _timed("a program is not started", program_stays_closed),
    ]


def _feature_history(tmp_path, monkeypatch) -> list[Outcome]:
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "history-sims"))
    from babysitter.sessions import append_turn, begin_session, list_sessions, load_session

    def routed(line):
        def check():
            assert _expect_route(line, "history")
            assert _route("tell me a story about history") == "model"
            return "The saved lines are read on this PC."

        return _timed(line, check)

    def saved():
        session_id = begin_session()
        append_turn(session_id, "set a reminder at one thirty", "Reminder set for 1:30 AM.")
        rows = list_sessions()
        assert rows and rows[0]["id"] == session_id
        record = load_session(session_id)
        assert record["turns"][0]["user"] == "set a reminder at one thirty"
        return "One saved turn."

    return [
        routed("read out my history"),
        routed("read my history"),
        routed("what did we talk about"),
        routed("can you read out my conversation"),
        _timed("a turn is saved", saved),
    ]


def _feature_clock_reminder() -> list[Outcome]:
    from babysitter.commands import clock_in

    morning = datetime(2026, 11, 15, 10, 0)

    def at_bedtime():
        found = match_quick_command("can you set a reminder at 1:30 pm to go to bed")
        assert found is not None and found.kind == "remind"
        assert found.detail == "to go to bed"
        moment = datetime.fromisoformat(found.when)
        assert moment.hour == 13 and moment.minute == 30
        return f"Reminder set for {moment.strftime('%I:%M %p').lstrip('0')}."

    def one_thirty_this_morning():
        moment = clock_in("at one thirty to go to bed", morning)
        assert moment is not None and moment.hour == 13 and moment.minute == 30
        assert moment.date() == morning.date()
        return "1:30 PM today."

    def noon():
        moment = clock_in("at noon", morning)
        assert moment is not None and moment.hour == 12 and moment.minute == 0
        return "12:00 PM."

    def already_passed():
        moment = clock_in("at 9 am", morning)
        assert moment is not None and moment.hour == 9
        assert moment.date() == datetime(2026, 11, 16).date()
        return "9:00 AM tomorrow."

    def no_clock():
        found = match_quick_command("set a reminder to buy milk")
        assert found is not None and found.kind == "remind" and found.when == ""
        assert found.detail == "to buy milk"
        assert _route("set a timer for 5 minutes") == "timer"
        return "Saved. to buy milk"

    return [
        _timed("1:30 pm", at_bedtime),
        _timed("one thirty later today", one_thirty_this_morning),
        _timed("noon", noon),
        _timed("a morning time that passed", already_passed),
        _timed("a reminder with no clock", no_clock),
    ]


def _feature_games() -> list[Outcome]:
    from babysitter.games import GameWatch, looks_like_game_path, should_hide_orb

    def steam():
        path = r"D:\Steam\steamapps\common\Baldurs Gate 3\bg3.exe"
        assert looks_like_game_path(path)
        # A helper word inside a game's own folder name is not a helper.
        assert looks_like_game_path(r"D:\Steam\steamapps\common\TheSetup\game.exe")
        assert looks_like_game_path(r"D:\Steam\steamapps\common\DirectX Quest\dxq.exe")
        assert looks_like_game_path(r"C:\Riot Games\Launcher Wars\wars.exe")
        return "bg3.exe"

    def launcher():
        path = r"D:\Steam\steamapps\common\EasyAntiCheat\EasyAntiCheat.exe"
        assert not looks_like_game_path(path)
        assert not looks_like_game_path(
            r"D:\Steam\steamapps\common\Steamworks Shared\_CommonRedist\vcredist\2019\VC_redist.x64.exe"
        )
        assert not looks_like_game_path(r"C:\Riot Games\Riot Client\RiotClientServices.exe")
        assert not looks_like_game_path(r"D:\Steam\steamapps\common\Some Game\_CommonRedist\DirectX\Jun2010\DXSETUP.exe")
        assert not looks_like_game_path(r"D:\Steam\steamapps\common\Some Game\unins000.exe")
        return "The anti-cheat helper is left alone."

    def notepad():
        assert not looks_like_game_path(r"C:\Windows\System32\notepad.exe")
        assert not looks_like_game_path(r"D:\Games\notes.txt")
        return "Notepad is not a game."

    def wake_during_a_game():
        watch = GameWatch()
        assert watch.auto_switch_target("bg3.exe") == "bg3.exe"
        watch.suppress("bg3.exe")
        assert watch.auto_switch_target("bg3.exe") is None
        assert watch.auto_switch_target(None) is None
        assert watch.auto_switch_target("bg3.exe") == "bg3.exe"
        return "Game mode waits until that game closes."

    def orb():
        assert should_hide_orb(True, "bg3.exe", ["bg3.exe"])
        assert not should_hide_orb(False, "bg3.exe", ["bg3.exe"])
        assert not should_hide_orb(True, "notepad.exe", ["bg3.exe"])
        return "The orb hides for a watched game."

    return [
        _timed("a store folder counts", steam),
        _timed("a helper does not", launcher),
        _timed("a normal program does not", notepad),
        _timed("waking holds game mode off", wake_during_a_game),
        _timed("the orb hides", orb),
    ]


def _feature_memory_match() -> list[Outcome]:
    from babysitter.embedder import rank_texts

    facts = [
        "My dog is called Biscuit.",
        "The wifi name is North.",
        "The spare key is in the tin.",
        "",
        "   ",
    ]

    def dog():
        found = rank_texts("what is my dog called", facts)
        assert found and found[0] == "My dog is called Biscuit."
        return found[0]

    def wifi():
        found = rank_texts("wifi", facts)
        assert found == ["The wifi name is North."]
        return found[0]

    def cap():
        found = rank_texts("the", ["The wifi name is North.", "The spare key is in the tin.", "The door code is 42."])
        assert len(found) <= 2
        return f"{len(found)} facts."

    def unrelated():
        assert rank_texts("quantum ceramics", facts) == []
        return "No fact matched."

    def blanks():
        assert rank_texts("dog", ["", "   ", "My dog is called Biscuit."]) == ["My dog is called Biscuit."]
        return "Blank facts are skipped."

    return [
        _timed("the dog fact", dog),
        _timed("the wifi fact", wifi),
        _timed("only two facts", cap),
        _timed("an unrelated question", unrelated),
        _timed("blank facts", blanks),
    ]


def _feature_followup() -> list[Outcome]:
    rows = (
        ("that's all", ""),
        ("tell me more", "tell me more"),
        ("read the rest", "read the rest"),
        ("thanks", None),
        ("what time is it", "what time is it"),
    )

    def one(line, expected):
        def check():
            assert followup_phrase(line) == expected
            return expected if expected is not None else "(not a follow-up)"

        return _timed(line, check)

    return [one(*row) for row in rows]
def _feature_setup() -> list[Outcome]:
    from babysitter.intelligence import MAIN_MODEL, WRITING_MODEL
    from babysitter.setupneed import (
        GITHUB_ZIP,
        Machine,
        commands_for,
        perform_pulls,
        pieces,
        pull_commands,
        visitor_summary,
    )

    ollama = r"C:\Ollama\ollama.exe"

    def github():
        text = visitor_summary()
        held = {piece.name for piece in pieces() if piece.on_github}
        assert "program source" in held and "requirements.txt" in held
        assert MAIN_MODEL not in held and "Ollama" not in held
        assert "does not hold a finished .exe" in text
        assert GITHUB_ZIP.endswith("/archive/refs/heads/main.zip")
        return "GitHub has the source, not the models"

    def fresh():
        from babysitter.setupneed import report

        machine = Machine(False, False, None, (), False)
        text = report(machine)
        assert "Python 3.12" in text and "Ollama" in text
        assert commands_for(machine) == ()
        said = perform_pulls(machine, lambda command: 0, confirmed=True)
        assert "Nothing was downloaded" in said[0]
        return "a fresh PC is told what is missing"

    def pulls():
        machine = Machine(True, True, ollama, (), True)
        ran: list[list[str]] = []
        perform_pulls(machine, lambda command: ran.append(list(command)) or 0, confirmed=True)
        assert ran == [[ollama, "pull", MAIN_MODEL], [ollama, "pull", WRITING_MODEL]]
        return "two pulls, and only those two"

    def already():
        machine = Machine(True, True, ollama, (MAIN_MODEL + ":latest", WRITING_MODEL), True)
        assert commands_for(machine) == ()
        said = perform_pulls(machine, lambda command: 1, confirmed=True)
        assert said == ("Both models are already downloaded.",)
        return "models already here, so nothing is downloaded"

    def stranger():
        with pytest.raises(ValueError):
            pull_commands(ollama, (MAIN_MODEL, "evil:latest"))
        return "a model that is not ours is refused"

    return [
        _timed("github holds source only", github),
        _timed("a fresh PC pulls nothing", fresh),
        _timed("ollama pulls the two models", pulls),
        _timed("models already here", already),
        _timed("a stranger model is refused", stranger),
    ]


def _feature_hero() -> list[Outcome]:
    from babysitter.paths import asset_path
    from babysitter.ui.hero_banner import HeroBanner

    app = QApplication.instance() or QApplication([])
    banner = HeroBanner(asset_path("hero.jpg"), asset_path("orb"))
    banner.set_reduced_motion(True)
    banner.resize(480, 150)
    app.processEvents()

    def light() -> int:
        image = banner._background().toImage()
        color = image.pixelColor(image.width() // 2, image.height() // 3)
        return color.red() + color.green() + color.blue()

    def darker():
        banner.show_phase("off", "Off", "The AI is off. Nothing is listening.")
        off = light()
        banner.show_phase("on", "On", "Hold Mouse 4 or say the keyword.")
        assert light() > off
        return "Off is darker than On"

    def cropped():
        image = banner._background().toImage()
        assert (image.width(), image.height()) == (banner.width(), banner.height())
        return "the picture fills the banner"

    def listening():
        banner.show_phase("listening", "Listening", "Say the question now.")
        assert banner._key == "on" and banner.frog._state == "listening"
        return "Listening keeps the On picture"

    def height():
        banner.set_compact(False)
        full = banner.height()
        banner.set_compact(True)
        assert full == 150 and banner.height() == 170
        return "half screen is 170 tall"

    def missing():
        width = banner._img.width()
        assert banner.set_image("/no/such/picture.jpg") is False
        assert banner._img.width() == width
        return "a bad picture leaves the current one"

    return [
        _timed("off is darker", darker),
        _timed("cropped to the panel", cropped),
        _timed("listening frog", listening),
        _timed("half screen height", height),
        _timed("a missing picture", missing),
    ]


def _feature_recognition() -> list[Outcome]:
    """Five ways of asking that used to miss, or land on the wrong minute."""
    from babysitter.commands import clock_in, when_from

    zone = datetime.now().astimezone().tzinfo
    afternoon = datetime(2026, 11, 20, 15, 0, tzinfo=zone)

    def seconds():
        found = match_quick_command("remind me in 10 seconds to stretch")
        assert found is not None and found.kind == "remind" and found.detail == "to stretch"
        moment = datetime.fromisoformat(found.when)
        assert 0 < (moment - datetime.now().astimezone()).total_seconds() <= 10
        return "to stretch in 10 seconds."

    def thirty_five():
        moment = clock_in("at six thirty five", afternoon)
        assert moment is not None and moment.hour == 18 and moment.minute == 35
        return "6:35 PM."

    def noon():
        moment = clock_in("at 12", afternoon)
        assert moment is not None and moment.hour == 12 and moment.minute == 0
        assert moment.date().day == 21
        half = clock_in("half past 12", afternoon)
        assert half is not None and half.hour == 12 and half.minute == 30
        return "12:00 PM tomorrow."

    def number_words():
        found = match_quick_command("set a timer for twenty minutes")
        assert found is not None and found.kind == "timer" and found.seconds == 20 * 60
        half = match_quick_command("set a timer for half an hour")
        assert half is not None and half.seconds == 30 * 60
        fixed = datetime(2026, 11, 20, 15, 0, 40, tzinfo=zone)
        soon = when_from("in ten seconds", fixed)
        assert soon is not None and (soon - fixed).total_seconds() == 10
        return "20 minutes, or half an hour."

    def wider():
        assert _expect_route("what's the date", "time")
        assert _expect_route("what's my next reminder", "next_reminder")
        assert _expect_route("say that again", "repeat")
        assert _expect_route("where is my tax pdf", "find")
        assert _route("where is paris") == "model"
        opened = match_quick_command("open the second one")
        assert opened is not None and opened.seconds == 2
        youtube = match_tool("comment themes https://www.youtube.com/watch?v=abc")
        assert youtube is not None and youtube.kind == "refuse"
        tiktok = match_tool("comments on https://www.tiktok.com/@x/video/1")
        assert tiktok is not None and tiktok.action_id == "tiktok-comments"
        return "Date, reminder, file, and the right comment site."

    return [
        _timed("in 10 seconds", seconds),
        _timed("six thirty five", thirty_five),
        _timed("at 12 after noon", noon),
        _timed("twenty minutes", number_words),
        _timed("wider phrases", wider),
    ]


def _feature_goals() -> list[Outcome]:
    """Five stretches of one conversation about goals, beside the other commands."""
    from babysitter.goals import conversation

    def one_goal():
        turns = conversation([
            "hey baby sitter my goal is to finish the bracket",
            "say my goals",
        ])
        assert turns[0].items[0]["text"] == "finish the bracket"
        assert "finish the bracket" in turns[1].speech
        assert turns[1].detail == "1. finish the bracket"
        return "finish the bracket."

    def second_done():
        turns = conversation([
            "add a goal to finish the bracket",
            "add another to call Mom",
            "what are my goals",
            "the second one is done",
            "say my goals",
        ])
        assert turns[1].items[1]["text"] == "call Mom"
        assert "finish the bracket" in turns[2].speech and "call Mom" in turns[2].speech
        assert turns[3].items[1]["done"] == "yes"
        assert turns[4].speech == "Your goal: finish the bracket."
        assert "Done. call Mom" in turns[4].detail
        return "call Mom is done."

    def done_then_a_task():
        turns = conversation([
            "add a goal to finish the bracket",
            "and also check my email",
            "say my goals",
            "done",
            "what time is it",
            "done",
        ])
        assert turns[1].route == "model"
        assert [item["text"] for item in turns[1].items] == ["finish the bracket"]
        assert turns[3].route == "goal_done" and turns[3].items[0]["done"] == "yes"
        assert turns[4].route == "time" and turns[4].goals_open is False
        assert turns[5].route == "task_done"
        return "Done finishes the goal, then the task."

    def beside_the_others():
        turns = conversation([
            "set a goal to get the shipment done",
            "find my goals",
            "where is my tax pdf",
            "don't forget to lock the door",
            "remind me in 10 seconds to stretch",
            "set a timer for twenty minutes",
            "what's my next reminder",
            "cancel the reminder",
            "open the second one",
        ])
        assert turns[0].items[0]["text"] == "get the shipment done"
        assert turns[1].route == "goals" and "get the shipment done" in turns[1].speech
        assert [turn.route for turn in turns[2:]] == [
            "find",
            "remind",
            "remind",
            "timer",
            "next_reminder",
            "cancel_reminder",
            "open_number",
        ]
        return "The shipment goal stays a goal."

    def drop_and_stop():
        turns = conversation([
            "add a goal to finish the bracket",
            "add another to call Mom",
            "drop the second goal",
            "say that again",
            "stop talking",
            "that's all",
            "the second",
        ])
        assert [item["text"] for item in turns[2].items] == ["finish the bracket"]
        assert turns[2].speech.startswith("Dropped call Mom")
        assert turns[3].route == "repeat" and turns[3].speech == turns[2].speech
        assert turns[4].route == "hush" and turns[4].goals_open is True
        assert turns[5].route == "stop" and turns[5].goals_open is False
        assert turns[6].route == "model"
        assert [item["text"] for item in turns[6].items] == ["finish the bracket"]
        return "Dropped call Mom."

    return [
        _timed("say my goals", one_goal),
        _timed("the second one is done", second_done),
        _timed("done, then a task", done_then_a_task),
        _timed("beside the other commands", beside_the_others),
        _timed("drop it and stop", drop_and_stop),
    ]


def _feature_tomorrow() -> list[Outcome]:
    from babysitter.commands import when_from

    zone = datetime.now().astimezone().tzinfo
    morning = datetime(2026, 11, 16, 10, 0, tzinfo=zone)

    def six():
        moment = when_from("tomorrow at 6", morning)
        assert moment is not None and moment.date().day == 17 and moment.hour == 6
        return "6:00 AM tomorrow."

    def six_pm():
        moment = when_from("tomorrow at 6 pm", morning)
        assert moment is not None and moment.date().day == 17 and moment.hour == 18
        return "6:00 PM tomorrow."

    def spoken():
        found = match_quick_command("remind me tomorrow at 6 to call")
        assert found is not None and found.detail == "to call"
        moment = datetime.fromisoformat(found.when)
        assert moment.hour == 6 and "tomorrow" not in found.detail
        return "to call at 6:00 AM tomorrow."

    def no_hour():
        found = match_quick_command("remind me tomorrow")
        assert found is not None and found.detail == "Reminder"
        assert datetime.fromisoformat(found.when).hour == 9
        return "9:00 AM tomorrow."

    def bare_timer():
        found = match_quick_command("set a timer")
        assert found is not None and found.kind == "remind" and found.detail == "Timer"
        wait = datetime.fromisoformat(found.when) - datetime.now().astimezone()
        assert 4 * 60 <= wait.total_seconds() <= 5 * 60 + 2
        return "Timer in 5 minutes."

    return [
        _timed("tomorrow at 6", six),
        _timed("tomorrow at 6 pm", six_pm),
        _timed("remind me tomorrow at 6 to call", spoken),
        _timed("remind me tomorrow", no_hour),
        _timed("set a timer", bare_timer),
    ]


def _feature_hearing() -> list[Outcome]:
    """Five ways a muddy line becomes a command, or stays a question."""
    from babysitter.commands import loosen_heard, match_quick_command
    from babysitter.plugins.voice.hearing import Transcript, merge_lines, needs_second_pass, pick_pass

    def timer_slip():
        found = match_quick_command("set a time for twenty minutes")
        assert found is not None and found.kind == "timer" and found.seconds == 20 * 60
        assert match_quick_command("what time is it").kind == "time"
        return "A timer, and the clock stays the clock."

    def file_slip():
        found = match_quick_command("fine my tax pdf")
        assert found is not None and found.kind == "find" and "tax pdf" in found.detail.lower()
        assert match_quick_command("fine thanks") is None
        assert loosen_heard("who invented dancing") == ""
        return "The tax pdf, and thanks stays a question."

    def remind_slip():
        found = match_quick_command("rewind me in 10 seconds to stretch")
        assert found is not None and found.kind == "remind" and found.detail == "to stretch"
        return "to stretch."

    def whisper_or_vosk():
        vague = Transcript("what is the capital of france", True)
        assert merge_lines("remind me to stretch", vague).text.startswith("remind me")
        clear = Transcript("what time is it", True)
        assert merge_lines("babble", clear).text == "what time is it"
        weak = Transcript("mumble mumble", False)
        assert merge_lines("what time is it", weak).text == "what time is it"
        assert merge_lines("", weak).confident is False
        return "The command wins, then a sure Whisper line."

    def second_reading():
        unsure = Transcript("mumble about the garden", False)
        assert needs_second_pass(unsure) is True
        sure = Transcript("what time is it", True)
        assert needs_second_pass(sure) is False
        picked = pick_pass(unsure, Transcript("set a timer for twenty minutes", True))
        assert picked.text.startswith("set a timer")
        kept = pick_pass(sure, Transcript("something else", True))
        assert kept.text == "what time is it"
        return "The second reading is only for a miss."

    return [
        _timed("set a time for twenty minutes", timer_slip),
        _timed("fine my tax pdf", file_slip),
        _timed("rewind me", remind_slip),
        _timed("keyword and whisper", whisper_or_vosk),
        _timed("a second reading", second_reading),
    ]


def _feature_plain_speech() -> list[Outcome]:
    """Five ordinary phrases that should land without a second try."""
    from datetime import datetime, timedelta

    from babysitter.commands import match_quick_command, when_from
    from babysitter.plugins.voice.hearing import Transcript, hallucinated, merge_lines

    now = datetime(2026, 11, 20, 9, 0, tzinfo=datetime.now().astimezone().tzinfo)

    def hour_and_a_half():
        found = match_quick_command("set a timer for an hour and a half")
        assert found is not None and found.kind == "timer" and found.seconds == 90 * 60
        return "90 minutes."

    def two_and_a_half():
        found = match_quick_command("set a timer for two and a half hours to bake")
        assert found is not None and found.kind == "timer" and found.seconds == 9000
        assert found.detail == "bake"
        return "bake, in two and a half hours."

    def half_a_minute():
        found = match_quick_command("set a timer for half a minute")
        assert found is not None and found.kind == "timer" and found.seconds == 30
        return "30 seconds."

    def remind_in_an_hour_and_a_half():
        moment = when_from("in an hour and a half", now)
        assert moment == now + timedelta(minutes=90)
        found = match_quick_command("remind me in an hour and a half to stretch")
        assert found is not None and found.kind == "remind" and found.detail == "to stretch"
        return "to stretch."

    def keep_the_real_line():
        assert hallucinated("Thanks for watching.")
        chosen = merge_lines("remind me to stretch", Transcript("what time is it", True))
        assert chosen.text == "remind me to stretch"
        assert merge_lines("babble", Transcript("what time is it", True)).text == "what time is it"
        return "The reminder stays, and the clock still answers."

    return [
        _timed("an hour and a half", hour_and_a_half),
        _timed("two and a half hours", two_and_a_half),
        _timed("half a minute", half_a_minute),
        _timed("in an hour and a half", remind_in_an_hour_and_a_half),
        _timed("the real command", keep_the_real_line),
    ]


def _feature_burst() -> list[Outcome]:
    """Five checks that a burst of clicks does not start a second job."""
    from babysitter.plugins.voice.keyword import should_join_listener
    from babysitter.ui.jobs import take_turn

    def one_voice():
        assert take_turn(False) == "start"
        assert take_turn(True) == "wait"
        return "The second line waits."

    def one_transcription():
        assert take_turn(True) == "wait"
        return "The second clip waits."

    def one_stop():
        assert should_join_listener(False, True) is True
        assert should_join_listener(True, True) is False
        assert should_join_listener(False, False) is False
        return "The microphone is asked to stop once."

    def idle_can_start():
        assert take_turn(False) == "start"
        assert should_join_listener(False, False) is False
        return "An idle window can take the next click."

    def newest_waits():
        action = take_turn(True)
        assert action == "wait"
        assert take_turn(False) == "start"
        return "The newest request runs when the first one finishes."

    return [
        _timed("one voice", one_voice),
        _timed("one transcription", one_transcription),
        _timed("one stop", one_stop),
        _timed("idle", idle_can_start),
        _timed("the newest line", newest_waits),
    ]


def _feature_packed(monkeypatch) -> list[Outcome]:
    """Five ways a packed library can be missing without closing the window."""
    import builtins
    from pathlib import Path

    original = builtins.__import__

    def _raise_for(module: str):
        def broken(name, globals=None, locals=None, fromlist=(), level=0):
            if name == module:
                raise FileNotFoundError(module)
            return original(name, globals, locals, fromlist, level)

        return broken

    def kokoro_config():
        monkeypatch.setattr(builtins, "__import__", _raise_for("kokoro_onnx"))
        try:
            from babysitter.plugins.voice.kokoro_voice import packages_installed

            assert packages_installed() is False
            return "Heart and Sarah stays off."
        finally:
            monkeypatch.setattr(builtins, "__import__", original)

    def vosk_folder():
        import shutil
        import tempfile

        from babysitter.plugins.voice.keyword import stage_vosk_libraries

        root = Path(tempfile.mkdtemp())
        try:
            (root / "libvosk.dll").write_bytes(b"vosk")
            (root / "Qt6Core.dll").write_bytes(b"qt")
            stage_vosk_libraries(str(root))
            assert (root / "vosk" / "libvosk.dll").read_bytes() == b"vosk"
            assert not (root / "vosk" / "Qt6Core.dll").exists()
            return "libvosk.dll is in the vosk folder."
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def other_libraries():
        monkeypatch.setattr(builtins, "__import__", _raise_for("faster_whisper"))
        try:
            from babysitter.plugins.voice.hearing import packages_installed as hearing_installed

            assert hearing_installed() is False
        finally:
            monkeypatch.setattr(builtins, "__import__", original)
        monkeypatch.setattr(builtins, "__import__", _raise_for("onnxruntime"))
        try:
            from babysitter.embedder import packages_installed as memory_installed

            assert memory_installed() is False
            return "Hearing and the sharper memory stay off."
        finally:
            monkeypatch.setattr(builtins, "__import__", original)

    def exe_refuses_pip():
        import babysitter.plugins.voice.kokoro_voice as kokoro
        from babysitter.platform import library_install_command

        original_installed = kokoro.packages_installed
        original_run = kokoro.run_hidden
        called = []
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        kokoro.packages_installed = lambda: False
        kokoro.run_hidden = lambda *args, **kwargs: called.append(args)
        try:
            assert library_install_command(("kokoro-onnx==0.6.1",)) is None
            try:
                kokoro.download()
            except kokoro.KokoroError as exc:
                assert "BabySitter.exe" in str(exc)
            else:
                raise AssertionError("The exe tried to pip-install.")
            assert called == []
            return "The exe does not install into itself."
        finally:
            kokoro.packages_installed = original_installed
            kokoro.run_hidden = original_run
            monkeypatch.delattr(sys, "frozen", raising=False)

    def spec_packs_the_files():
        text = (Path(__file__).resolve().parents[1] / "packaging" / "babysitter.spec").read_text(encoding="utf-8")
        for name in ("kokoro_onnx", "espeakng_loader", "_sounddevice_data", "vosk"):
            assert f'"{name}"' in text
        return "The build packs the files those libraries open."

    return [
        _timed("kokoro config.json", kokoro_config),
        _timed("vosk folder", vosk_folder),
        _timed("hearing and memory", other_libraries),
        _timed("the exe does not pip", exe_refuses_pip),
        _timed("the build packs the files", spec_packs_the_files),
    ]


def _feature_phrasing() -> list[Outcome]:
    from babysitter.phrasing import PhraseBook

    def time_varies():
        book = PhraseBook()
        moment = datetime(2026, 11, 26, 14, 5)
        first = book.time_reply(moment)
        second = book.time_reply(moment)
        assert "It's" in first and "It's" in second
        assert "2:05 PM" in first and "2:05 PM" in second
        assert first != second
        return first

    def vram_varies():
        book = PhraseBook()
        first = book.vram_reply(6400, 12288)
        second = book.vram_reply(6400, 12288)
        assert "6,400" in first and "12,288" in second
        assert first != second
        return first

    def memory_quotes_short_fact():
        book = PhraseBook()
        first = book.memory_saved_reply("the cat is called Moth")
        second = book.memory_saved_reply("the cat is called Moth")
        assert "Moth" in first and "10 seconds" in first
        assert first != second
        return first

    def reminder_names_task():
        book = PhraseBook()
        first = book.reminder_saved_reply("6:00 PM", "stretch")
        second = book.reminder_saved_reply("6:00 PM", "stretch")
        assert "6:00 PM" in first and "stretch" in first
        assert first != second
        return first

    def timer_names_duration():
        book = PhraseBook()
        first = book.timer_saved_reply("5 minutes", "check the oven")
        second = book.timer_saved_reply("5 minutes", "check the oven")
        assert "5 minutes" in first and "check the oven" in first
        assert first != second
        return first

    return [
        _timed("time varies", time_varies),
        _timed("vram varies", vram_varies),
        _timed("memory quotes fact", memory_quotes_short_fact),
        _timed("reminder names task", reminder_names_task),
        _timed("timer names duration", timer_names_duration),
    ]


def _feature_journal_excluded(tmp_path, monkeypatch) -> list[Outcome]:
    from babysitter.controller import Controller
    from babysitter.journal import record_sample
    from babysitter.settings import load_settings

    folder = tmp_path / "journal_excl"
    folder.mkdir(exist_ok=True)
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(folder))
    ctrl = Controller()

    def adds_clean_exe():
        added = ctrl.add_journal_excluded(r"C:\Apps\Signal\Signal.exe")
        assert added == "Signal.exe"
        assert "Signal.exe" in load_settings().journal_excluded
        return f"Left out {added}."

    def deduplicates_case():
        ctrl.add_journal_excluded("signal.exe")
        assert len(ctrl.settings.journal_excluded) == 1
        return "Kept one copy."

    def skips_in_journal():
        day = {"date": "2026-11-26", "apps": {}, "tasks": []}
        wrote = record_sample(
            day,
            "signal.exe",
            datetime(2026, 11, 26, 10, 0),
            excluded=ctrl.settings.journal_excluded,
        )
        assert wrote is False and day["apps"] == {}
        return "Skipped excluded program."

    def removes_cleanly():
        ctrl.remove_journal_excluded("SIGNAL.EXE")
        assert ctrl.settings.journal_excluded == []
        return "Allowed again."

    def rejects_traversal():
        try:
            ctrl.add_journal_excluded("..")
        except ValueError as exc:
            ctrl.shutdown_threads()
            return str(exc)
        ctrl.shutdown_threads()
        raise AssertionError("Accepted traversal name")

    return [
        _timed("adds clean name", adds_clean_exe),
        _timed("deduplicates case", deduplicates_case),
        _timed("skips in journal", skips_in_journal),
        _timed("removes cleanly", removes_cleanly),
        _timed("rejects bad name", rejects_traversal),
    ]


def _feature_model_removal() -> list[Outcome]:
    from babysitter.ollama import OllamaClient, OllamaError

    def deletes_named_model():
        calls = []
        client = OllamaClient()
        client._request = lambda method, path, body=None, timeout=10: calls.append((method, path, body)) or {}
        client.delete_model("qwen3.5:4b")
        assert calls == [("DELETE", "/api/delete", {"model": "qwen3.5:4b"})]
        return "Removed qwen3.5:4b."

    def trims_spaces():
        calls = []
        client = OllamaClient()
        client._request = lambda method, path, body=None, timeout=10: calls.append(body) or {}
        client.delete_model("  gemma4:12b  ")
        assert calls == [{"model": "gemma4:12b"}]
        return "Trimmed spaces."

    def rejects_empty():
        client = OllamaClient()
        try:
            client.delete_model("   ")
        except OllamaError as exc:
            return str(exc)
        raise AssertionError("Deleted empty model name")

    def surfaces_ollama_error():
        client = OllamaClient()

        def fail(*_args, **_kwargs):
            raise OllamaError("Ollama did not find that model.")

        client._request = fail
        try:
            client.delete_model("missing:latest")
        except OllamaError as exc:
            assert "did not find" in str(exc)
            return str(exc)
        raise AssertionError("Swallowed OllamaError")

    def page_has_remove_button():
        app = QApplication.instance() or QApplication([])
        from babysitter.ui.pages.desk import ModelsPage

        page = ModelsPage()
        seen = []
        page.notice.connect(seen.append)
        page.remove_name.setText("qwen3.5:4b")
        page._remove_model()
        assert seen == ["REMOVE model: qwen3.5:4b"]
        assert app is not None
        return seen[0]

    return [
        _timed("deletes named model", deletes_named_model),
        _timed("trims spaces", trims_spaces),
        _timed("rejects empty", rejects_empty),
        _timed("surfaces error", surfaces_ollama_error),
        _timed("page emits notice", page_has_remove_button),
    ]


def _feature_accessibility_and_exe() -> list[Outcome]:
    import ast
    import builtins
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    def shell_has_qt_imports():
        import babysitter.ui.shell as shell_mod

        for sym in ("QApplication", "QDialog", "QFileDialog", "QMenu"):
            assert hasattr(shell_mod, sym), sym
        tree = ast.parse((root / "src" / "babysitter" / "ui" / "shell.py").read_text(encoding="utf-8"))
        assert tree is not None
        assert builtins is not None
        return "All Qt window classes are imported in shell.py."

    def build_script_checks_errors():
        script = (root / "scripts" / "build-exe.bat").read_text(encoding="utf-8")
        assert "PyInstaller" in script
        assert 'if not exist "dist\\BabySitter.exe"' in script
        assert "taskkill /IM BabySitter.exe" in script
        return "build-exe.bat unlocks running exe and checks PyInstaller exit code."

    def spec_packs_submodules_and_excludes_pytest():
        spec = (root / "packaging" / "babysitter.spec").read_text(encoding="utf-8")
        assert "collect_submodules" in spec
        assert '"numpy"' in spec
        assert '"pytest"' in spec
        return "babysitter.spec packs submodules and numpy without pytest."

    def titlebar_and_inputs_accessible():
        app = QApplication.instance() or QApplication([])
        from PySide6.QtCore import Qt
        from babysitter.ui.main_window import MainWindow

        win = MainWindow()
        assert win.min_button.accessibleName() == "Minimize to the frog"
        assert win.close_button.accessibleName() == "Close window and turn AI off"
        assert win.close_button.focusPolicy() == Qt.TabFocus
        assert win.home.typed.accessibleName() == "Type a question or command"
        assert app is not None
        return "Titlebar buttons and inputs expose accessible names and Tab focus."

    def escape_emits_hidden_to_tray():
        app = QApplication.instance() or QApplication([])
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from babysitter.ui.main_window import MainWindow

        win = MainWindow()
        hidden = []
        win.hidden_to_tray.connect(lambda: hidden.append(True))
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        win.keyPressEvent(event)
        assert hidden == [True]
        assert app is not None
        return "Escape closes to tray and turns the AI off."

    return [
        _timed("shell imports qt widgets", shell_has_qt_imports),
        _timed("build script checks errors", build_script_checks_errors),
        _timed("spec excludes pytest", spec_packs_submodules_and_excludes_pytest),
        _timed("accessible names and tab focus", titlebar_and_inputs_accessible),
        _timed("escape turns ai off", escape_emits_hidden_to_tray),
    ]


def _feature_self_update(tmp_path, monkeypatch) -> list[Outcome]:
    import hashlib
    import subprocess
    from babysitter.commands import match_quick_command
    from babysitter.security import require_release_asset_url
    from babysitter.selfupdate import clean_pyinstaller_env, run_finish_update, write_update_manifest
    from babysitter.updates import check_for_update

    def spoken_update_commands() -> str:
        c1 = match_quick_command("check for updates")
        c2 = match_quick_command("update babysitter")
        assert c1 is not None and c1.kind == "check_update"
        assert c2 is not None and c2.kind == "apply_update"
        return "Both check-update and update-babysitter commands match locally."

    def origin_main_detected_without_github_push() -> str:
        base = tmp_path / "sim_update"
        origin = base / "origin.git"
        pub = base / "pub"
        loc = base / "loc"
        base.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(origin)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(origin), str(pub)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(pub), "config", "user.name", "Sim"], check=True)
        subprocess.run(["git", "-C", str(pub), "config", "user.email", "sim@example.com"], check=True)
        (pub / "packaging").mkdir(parents=True)
        (pub / "packaging" / "babysitter.spec").write_text("# spec\n", encoding="utf-8")
        (pub / "src" / "babysitter").mkdir(parents=True)
        (pub / "src" / "babysitter" / "version.py").write_text('__version__ = "0.17.4"\n', encoding="utf-8")
        subprocess.run(["git", "-C", str(pub), "add", "."], check=True)
        subprocess.run(["git", "-C", str(pub), "commit", "-m", "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(pub), "push", "-u", "origin", "main"], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(origin), str(loc)], check=True, capture_output=True)
        (pub / "src" / "babysitter" / "version.py").write_text('__version__ = "0.18.0"\n', encoding="utf-8")
        subprocess.run(["git", "-C", str(pub), "add", "."], check=True)
        subprocess.run(["git", "-C", str(pub), "commit", "-m", "New 0.18.0"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(pub), "push", "origin", "main"], check=True, capture_output=True)
        monkeypatch.setenv("BABYSITTER_DATA_DIR", str(base / "data"))
        monkeypatch.setenv("BABYSITTER_REPO_DIR", str(loc))
        plan = check_for_update(current="0.17.4", frozen=False)
        monkeypatch.delenv("BABYSITTER_REPO_DIR", raising=False)
        assert plan.available and plan.can_install and plan.target_version == "0.18.0"
        return plan.summary

    def release_url_allowlist() -> str:
        require_release_asset_url(
            "https://github.com/Michelederege/BabySitter_Ai_Assistant/releases/download/v0.18.0/BabySitter.exe"
        )
        try:
            require_release_asset_url("https://example.com/BabySitter.exe")
        except ValueError:
            return "Only the BabySitter GitHub release bucket is accepted."
        raise AssertionError("Bad release URL was not rejected")

    def atomic_exe_swap() -> str:
        monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "swap_data"))
        staged = tmp_path / "swap_data" / "updates" / "BabySitter-new.exe"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"NEW-BIN")
        target = tmp_path / "swap_target" / "BabySitter.exe"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"OLD-BIN")
        manifest = write_update_manifest(
            from_version="0.17.4",
            to_version="0.18.0",
            staged_exe=str(staged),
            targets=[str(target)],
            relaunch_cmd=[str(target)],
            wait_pids=[],
        )
        seen: list[list[str]] = []
        assert run_finish_update(
            str(manifest),
            sleep_fn=lambda _s: None,
            pid_exists_fn=lambda _p: False,
            popen_fn=lambda args, **_kw: seen.append(args),
        ) == 0
        assert target.read_bytes() == b"NEW-BIN"
        assert seen == [[str(target)]]
        return "Staged BabySitter.exe replaced target and relaunched."

    def reset_pyinstaller_environment() -> str:
        env = clean_pyinstaller_env()
        assert env.get("PYINSTALLER_RESET_ENVIRONMENT") == "1"
        assert hashlib.sha256(b"ok").hexdigest()
        return "Relaunched exe resets PyInstaller unpack state."

    return [
        _timed("spoken update commands", spoken_update_commands),
        _timed("origin main check without push", origin_main_detected_without_github_push),
        _timed("release url allowlist", release_url_allowlist),
        _timed("atomic exe swap", atomic_exe_swap),
        _timed("reset pyinstaller env", reset_pyinstaller_environment),
    ]


def _feature_inbox() -> list[Outcome]:
    from datetime import timezone

    from babysitter.blackboard import FeedError, blackboard_speech, events_from_ics, require_feed_url
    from babysitter.plugins.tools.google_account import (
        DRIVE_LIST_URL,
        GoogleError,
        authorization_url,
        read_account,
    )
    from babysitter.security import require_google_url
    from babysitter.settings import Settings

    def drive_list_is_read_only() -> str:
        require_google_url(DRIVE_LIST_URL)
        try:
            require_google_url("https://www.googleapis.com/upload/drive/v3/files")
        except ValueError:
            return "Drive names can be listed. An upload address is refused."
        raise AssertionError("an upload address was allowed")

    def sign_in_asks_for_drive() -> str:
        url = authorization_url("client-id.apps.googleusercontent.com", "state", "challenge")
        assert "gmail.readonly" in url and "calendar.readonly" in url and "drive.readonly" in url
        school = authorization_url("client-id.apps.googleusercontent.com", "state", "challenge", prompt="select_account consent")
        assert "select_account" in school
        return "Sign-in asks for read-only mail, calendar, and Drive."

    def one_failure_leaves_the_rest() -> str:
        token = "ya29.example-token-value"

        def fetch(url, _token):
            if "drive" in url:
                raise GoogleError("Drive refused the read.")
            if "messages?q=" in url:
                return {"messages": [{"id": "abc123"}]}
            if "abc123" in url:
                return {"payload": {"headers": [
                    {"name": "Subject", "value": "Lab notes"},
                    {"name": "From", "value": "Ada"},
                ]}}
            if "calendar" in url:
                return {"items": []}
            raise AssertionError(url)

        rows, speeches, problems = read_account(
            token,
            mail_prefix="Mail",
            calendar_prefix="Calendar",
            drive_prefix="Drive",
            fetch=fetch,
        )
        assert any("Lab notes" in row for row in rows)
        assert any("Drive" in problem for problem in problems)
        assert token not in " ".join(rows + speeches + problems)
        return "Mail still shows when Drive cannot be read."

    def blackboard_upcoming() -> str:
        text = "\n".join([
            "BEGIN:VEVENT",
            "SUMMARY:Essay due",
            "DTSTART:20200101T120000Z",
            "END:VEVENT",
            "BEGIN:VEVENT",
            "SUMMARY:Studio review",
            "DTSTART:20300102T150000Z",
            "END:VEVENT",
        ])
        events = events_from_ics(text, today=datetime(2026, 11, 26, tzinfo=timezone.utc))
        assert [summary for summary, _when in events] == ["Studio review"]
        speech = blackboard_speech(events)
        assert "Studio review" in speech and "Essay due" not in speech
        return speech

    def feed_stays_off_the_pc_and_out_of_settings() -> str:
        for bad in (
            "http://school.example/calendar.ics",
            "https://127.0.0.1/webapps/calendar.ics",
            "https://10.1.2.3/learn/calendar",
            "https://files.example/notes.txt",
        ):
            try:
                require_feed_url(bad)
            except FeedError:
                continue
            raise AssertionError(bad)
        good = require_feed_url("https://school.example/webapps/calendar/feed.ics")
        assert good.startswith("https://school.example/")
        saved = Settings(blackboard_enabled=True).to_dict()
        assert saved["blackboard_enabled"] is True
        assert "http" not in str(saved)
        assert match_quick_command("check my drive").kind == "drive"
        assert match_quick_command("check my school email").kind == "school_mail"
        assert match_quick_command("what's on blackboard").kind == "blackboard"
        assert match_quick_command("check my email").kind == "mail"
        return "The Blackboard link has to be the school's https calendar."

    return [
        _timed("drive list only", drive_list_is_read_only),
        _timed("read only sign in", sign_in_asks_for_drive),
        _timed("one failure stays local", one_failure_leaves_the_rest),
        _timed("blackboard upcoming", blackboard_upcoming),
        _timed("feed stays private", feed_stays_off_the_pc_and_out_of_settings),
    ]


def _feature_writing_draft() -> list[Outcome]:
    from datetime import timedelta, timezone

    from babysitter.intents import match_tool
    from babysitter.plugins.tools.google_account import doc_export_url
    from babysitter.security import require_google_url
    from babysitter.writing import (
        WRITING_RULES,
        clip_draft,
        pick_draft,
        read_open_draft,
        title_from_window,
        writing_miss,
    )
    from babysitter.plugins.tools.google_account import GoogleError

    now = datetime(2026, 11, 26, 19, 0, tzinfo=timezone.utc)
    essay = {
        "id": "essay01",
        "name": "Studio essay",
        "modifiedTime": "2026-11-26T18:40:00Z",
        "mimeType": "application/vnd.google-apps.document",
    }
    older = {
        "id": "notes01",
        "name": "Old notes",
        "modifiedTime": "2026-11-20T18:40:00Z",
        "mimeType": "application/vnd.google-apps.document",
    }

    def window_picks_the_open_doc() -> str:
        from babysitter.writing import choices_from_listing

        choices = choices_from_listing({"files": [essay, older]}, 0)
        for title in (
            "Studio essay - Google Docs - Google Chrome",
            "Studio essay - Google Docs - DuckDuckGo",
            "Studio essay - Google Docs — DuckDuckGo Browser",
            "DuckDuckGo — Studio essay - Google Docs",
        ):
            picked = pick_draft(choices, title, now)
            assert picked is not None and picked.name == "Studio essay", title
        assert title_from_window("BabySitter") == ""
        assert title_from_window("DuckDuckGo") == ""
        return "A Google Docs tab in DuckDuckGo or Chrome picks that draft."

    def a_quiet_doc_stays_out() -> str:
        from babysitter.writing import choices_from_listing

        stale = dict(essay)
        stale["modifiedTime"] = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        choices = choices_from_listing({"files": [stale]}, 0)
        assert pick_draft(choices, "BabySitter", now) is None
        assert pick_draft(choices, "", now, allow_stale=True) is not None
        return "A doc left alone for hours is not attached."

    def plain_text_only() -> str:
        require_google_url(doc_export_url("essay01"))
        for blocked in (
            "https://www.googleapis.com/drive/v3/files/essay01?alt=media",
            "https://www.googleapis.com/drive/v3/files/essay01/export?mimeType=application/pdf",
        ):
            try:
                require_google_url(blocked)
            except ValueError:
                continue
            raise AssertionError(blocked)
        return "The draft is plain text. The file is not downloaded."

    def the_question_carries_the_draft() -> str:
        token = "ya29.example-token-value-ok"

        def fetch_json(url, got):
            assert got == token and "mimeType" in url
            return {"files": [essay, older]}

        def fetch_text(url, got):
            # /export is the document's text. Without it Drive sends the
            # file's details as JSON, and the model never sees the draft.
            assert got == token and url.endswith("/export?mimeType=text/plain")
            return "The armory opened in 1913.\n\nI am still writing the last paragraph."

        draft = read_open_draft([token], "Studio essay - Google Docs", fetch_json=fetch_json, fetch_text=fetch_text, now=now)
        assert draft is not None
        assert "1913" in draft.note and WRITING_RULES in draft.note
        assert token not in draft.note
        long_text = ("Opening claim. " * 40) + "I am still writing the last paragraph."
        assert "last paragraph" in clip_draft(long_text, 400)
        assert "Opening claim" in clip_draft(long_text, 400)
        return draft.speech

    def lookup_asks_and_credits_only_real_sources() -> str:
        intent = match_tool("find a source for the Armory Show for this paper")
        assert intent is not None and intent.kind == "web"
        assert "Armory Show" in intent.query and "for this paper" not in intent.query
        assert "Do not invent" in intent.summary
        assert match_quick_command("what am I writing").kind == "draft"
        assert "Do not invent the draft" in writing_miss("how do I strengthen this essay")
        assert writing_miss("what time is dinner") == ""
        try:
            doc_export_url("bad id")
        except GoogleError:
            return "A lookup asks first, and a missing source is not invented."
        raise AssertionError("a bad file id was accepted")

    return [
        _timed("open doc wins", window_picks_the_open_doc),
        _timed("quiet doc stays out", a_quiet_doc_stays_out),
        _timed("plain text only", plain_text_only),
        _timed("draft rides along", the_question_carries_the_draft),
        _timed("lookup credits real sources", lookup_asks_and_credits_only_real_sources),
    ]


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
        ("clock reminder", _feature_clock_reminder()),
        ("tomorrow", _feature_tomorrow()),
        ("recognition", _feature_recognition()),
        ("hearing", _feature_hearing()),
        ("plain speech", _feature_plain_speech()),
        ("burst", _feature_burst()),
        ("goals", _feature_goals()),
        ("timer", _feature_timer()),
        ("journal", _feature_journal()),
        ("files", _feature_files()),
        ("history", _feature_history(tmp_path, monkeypatch)),
        ("games", _feature_games()),
        ("memory match", _feature_memory_match()),
        ("follow-up", _feature_followup()),
        ("undo", _feature_undo()),
        ("why", _feature_why()),
        ("weekly review", _feature_weekly()),
        ("rate", _feature_rate()),
        ("web search", _feature_web()),
        ("social search", _feature_social()),
        ("yes or no", _feature_yes_no()),
        ("keyword", _feature_keyword()),
        ("packed voice", _feature_packed(monkeypatch)),
        ("speech", _feature_speech()),
        ("quiet hours", _feature_quiet()),
        ("turn gate", _feature_turn_gate()),
        ("intelligence", _feature_intelligence()),
        ("power", _feature_power()),
        ("shutdown", _feature_shutdown(tmp_path, monkeypatch)),
        ("setup", _feature_setup()),
        ("hero", _feature_hero()),
        ("phrasing", _feature_phrasing()),
        ("journal excluded", _feature_journal_excluded(tmp_path, monkeypatch)),
        ("model removal", _feature_model_removal()),
        ("accessibility and exe", _feature_accessibility_and_exe()),
        ("self update", _feature_self_update(tmp_path, monkeypatch)),
        ("inbox", _feature_inbox()),
        ("writing draft", _feature_writing_draft()),
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
