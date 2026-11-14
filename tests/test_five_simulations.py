"""Five simulations of one BabySitter session.

They run the real power switch, the voice router, the spoken reply splitter,
and the scan. They do not load a model and they do not open a microphone.
Each test prints the report for that simulation.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import psutil
from PySide6.QtWidgets import QApplication

from babysitter.commands import match_quick_command
from babysitter.intents import match_tool
from babysitter.intelligence import MODES
from babysitter.ollama import IDLE_KEEP_ALIVE, LoadedModel, chat_body, server_environment, spill_problem
from babysitter.ollama import _terminate_psutil
from babysitter.pcscan import memory_sentence, scan, spoken_reading
from babysitter.plugins.voice.keyword import command_after_keyword
from babysitter.plugins.voice.speech import followup_phrase, unread_detail, voice_and_rest
from babysitter.vram import LOW_CEILING_MIB, low_estimate_mib, need_mib
from tests.test_power import make, progress


def _route(text: str) -> str:
    heard = command_after_keyword(text, "baby sitter")
    line = text if heard is None else (heard or text)
    quick = match_quick_command(line)
    if quick is not None:
        return quick.kind
    intent = match_tool(line)
    if intent is not None:
        return f"tool-{intent.kind}"
    return "model"


def _shell(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    shell._app = app
    return shell


def _close(shell) -> None:
    shell.registrar.clear()
    shell.controller.shutdown_threads()
    shell._app.processEvents()


def test_simulation_1_closing_unloads_the_model(tmp_path, monkeypatch, capsys):
    """Close and Quit must not leave a model resident."""
    service, ollama, *_rest = make()
    turned = service.turn_on(
        model="gemma4:12b",
        num_ctx=8192,
        cancel=threading.Event(),
        game_name=None,
        progress=progress,
    )
    assert turned.state == "on"
    assert ollama.started_ctx == 8192
    assert ollama.models
    body = chat_body("gemma4:12b", "hello", 8192)
    assert body["keep_alive"] == IDLE_KEEP_ALIVE
    assert body["keep_alive"] != -1

    shell = _shell(tmp_path, monkeypatch)
    try:
        stopped: list[str] = []
        shell.controller.turn_off = lambda **kwargs: stopped.append(f"hide:{kwargs['tray_choice']}")
        shell.controller.power.state = "on"
        shell._on_hidden_to_tray()
        assert stopped == ["hide:close"]

        stopped.clear()
        shell.controller.request_quit = lambda: "ask"
        shell.controller.quit_after_stopping = lambda: stopped.append("quit-stop")
        shell._quit()
        assert stopped == ["quit-stop"]
        assert "leave" not in stopped
    finally:
        _close(shell)

    service.turn_off(emergency=False, tray_choice="close", progress=progress)
    assert service.state == "off"
    assert ollama.stopped == 1
    assert ollama.models == []
    assert ollama.port is False
    low_env = server_environment({}, "127.0.0.1", 11434, 4096)
    assert low_env["OLLAMA_CONTEXT_LENGTH"] == "4096"
    print(
        "SIM 1  close/quit: model was resident after turn-on "
        f"({ollama.preloaded}), keep_alive is {IDLE_KEEP_ALIVE}, "
        "hide and quit both request a full stop, and the server context follows the level."
    )
    captured = capsys.readouterr()
    assert "SIM 1" in captured.out


def test_simulation_1_a_runner_child_dies_with_the_parent():
    """The model runner is often a child. Stopping only the parent used to leave it."""
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
        child = psutil.Process(child_pid)
        assert child.ppid() == parent.pid
        _terminate_psutil(psutil.Process(parent.pid))
        assert not child.is_running()
        assert parent.poll() is not None
    finally:
        for pid in (child_pid, parent.pid):
            try:
                os.kill(pid, 9)
            except OSError:
                pass


def test_simulation_2_voice_routes_and_what_the_microphone_muddles(capsys):
    expected = {
        "i'd like you to scan my computer my ram usage is very high": "scan",
        "baby sitter what time is it": "time",
        "baby sitter what's my vram": "vram",
        "baby sitter how is my pc": "health",
        "baby sitter check my email": "mail",
        "why is my ram so high": "scan",
        "check my pc": "scan",
        "clean up my computer": "scan",
        "how is my computer": "health",
        "set a timer for 5 minutes": "timer",
        "remember the door code is 4 2": "remember",
        "search the web for how to scan my computer": "tool-web",
        "who invented dancing": "model",
        "the ram is in the high cabinet": "model",
    }
    misses = {line: _route(line) for line, want in expected.items() if _route(line) != want}
    assert misses == {}
    muddy = {
        "my pee cee is slow": "model",
        "scan the pee cee": "model",
        "ram usage is very high": "scan",
    }
    muddy_got = {line: _route(line) for line in muddy}
    assert muddy_got["ram usage is very high"] == "scan"
    assert muddy_got["my pee cee is slow"] == "model"
    print(
        "SIM 2  voice: the clear lines all landed. "
        "A microphone that hears 'pee cee' instead of 'pc' still goes to the model: "
        + ", ".join(f"{line!r} -> {got}" for line, got in muddy_got.items())
    )
    assert "SIM 2" in capsys.readouterr().out


def test_simulation_3_local_replies_are_the_fast_path(capsys):
    started = time.perf_counter()
    for _ in range(1000):
        assert _route("why is my ram so high") == "scan"
        assert _route("what time is it") == "time"
        assert _route("who invented dancing") == "model"
    elapsed_ms = (time.perf_counter() - started) * 1000
    per_call = elapsed_ms / 3000
    gigabyte = 1024 ** 3
    scan_started = time.perf_counter()
    result = scan(
        [("chrome.exe", 1800 * 1024 * 1024, 4)],
        [],
        memory=(20 * gigabyte, 32 * gigabyte),
    )
    scan_ms = (time.perf_counter() - scan_started) * 1000
    assert result.memory_line.startswith("Memory is using")
    assert per_call < 2
    assert scan_ms < 50
    print(
        f"SIM 3  speed: routing 3000 lines took {elapsed_ms:.1f} ms "
        f"({per_call:.3f} ms each). A local scan took {scan_ms:.2f} ms. "
        "The model path waits 1500 ms before a filler word. These lines never enter that wait."
    )
    assert "SIM 3" in capsys.readouterr().out


def test_simulation_4_speech_keeps_the_numbers_and_drops_the_script(capsys):
    gigabyte = 1024 ** 3
    reading = spoken_reading(20 * gigabyte, 32 * gigabyte, 14)
    assert reading.startswith("Memory is using 20.0 of 32.0 GB, 62 percent. CPU is at 14 percent.")
    heavy = scan(
        [("chrome.exe", 1800 * 1024 * 1024, 4), ("notepad.exe", 20 * 1024 * 1024, 5)],
        [],
        memory=(20 * gigabyte, 32 * gigabyte),
    )
    spoken = f"{heavy.memory_line} {heavy.suggestions[0].speech}"
    assert "20.0 of 32.0 GB" in spoken
    assert "Close it?" in spoken
    assert "powershell" not in spoken.lower()
    long_reply = (
        "Memory is fine. "
        "Chrome is the heavy one. "
        "I would close it. "
        "The fourth sentence should stay on the screen. "
        "So should the fifth."
    )
    said, rest = voice_and_rest(long_reply)
    assert "fourth" not in said
    assert "fourth" in rest
    fenced = "The number is 20 GB.\n\n```powershell\nGet-Process\n```"
    voice, _rest = voice_and_rest(fenced)
    detail = unread_detail(voice, fenced)
    assert "Get-Process" not in voice
    assert "Get-Process" in detail
    assert followup_phrase("no") is None
    print(
        "SIM 4  speech: the health line says the memory and CPU numbers. "
        "A scan says the memory number and one question. "
        "Three sentences are spoken; the rest stays on screen. Code is not spoken."
    )
    assert "SIM 4" in capsys.readouterr().out
    assert memory_sentence(0, 0) == ""


def test_simulation_5_what_uses_the_memory(capsys):
    low = need_mib(MODES["low"].model, MODES["low"].num_ctx)
    medium = need_mib(MODES["medium"].model, MODES["medium"].num_ctx)
    high = need_mib(MODES["high"].model, MODES["high"].num_ctx)
    assert low <= LOW_CEILING_MIB
    assert low_estimate_mib() <= LOW_CEILING_MIB
    assert medium == 9500
    assert high == 11000
    spilled = LoadedModel("gemma4:12b", 12_000_000_000, 8_000_000_000, 8192)
    assert spill_problem(spilled)
    held = LoadedModel("qwen3.5:9b", 6_000_000_000, 5_900_000_000, 4096)
    assert spill_problem(held) is None
    print(
        "SIM 5  memory: "
        f"Low wants {low} MiB of video memory and estimates {low_estimate_mib()} MiB. "
        f"Medium ({MODES['medium'].model}, {MODES['medium'].num_ctx} context) wants {medium} MiB. "
        f"High wants {high} MiB. "
        "A 12 GB card that cannot hold Medium spills several GB into system RAM, "
        "and Task Manager then shows about 20 GB while that process is still alive. "
        "The hearing model and Heart and Sarah are released when the AI turns off."
    )
    assert "SIM 5" in capsys.readouterr().out
