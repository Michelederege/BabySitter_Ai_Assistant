"""Spoken lines, routed the way a voice turn is routed.

These are the sentences a person actually says. A scan request has to stay
on this PC. It must not be handed to the model.
"""

from babysitter.commands import match_quick_command
from babysitter.intents import match_tool
from babysitter.ollama import system_prompt
from babysitter.pcscan import memory_sentence, scan, spoken_reading
from babysitter.plugins.voice.keyword import command_after_keyword
from babysitter.plugins.voice.speech import followup_phrase, unread_detail, voice_and_rest


HEARD = "i'd like you to scan my computer my ram usage is very high"

MODEL_REPLY = (
    "I can't actually scan your hardware directly since I'm just a voice interface on this PC. "
    "To help with your high RAM usage, could you tell me what programs are running right now?\n\n"
    "Below are some common steps to check and reduce memory usage:\n\n"
    "```powershell\n"
    "Get-Process | Sort-Object WorkingSet -Descending\n"
    "```\n\n"
    "You can also open Task Manager."
)


def route(text: str) -> str:
    """The gate in front of the model. Quick commands win, then tools."""
    quick = match_quick_command(text)
    if quick is not None:
        return quick.kind
    intent = match_tool(text)
    if intent is not None:
        return f"tool-{intent.kind}"
    return "model"


def test_the_spoken_scan_does_not_go_to_the_model():
    assert followup_phrase(HEARD) not in {"", None}
    assert route(HEARD) == "scan"
    polite = "I'd like you to scan my computer. My RAM usage is very high."
    assert route(polite) == "scan"
    after_keyword = command_after_keyword(
        "baby sitter I'd like you to scan my computer my ram usage is very high",
        "baby sitter",
    )
    assert route(after_keyword) == "scan"


def test_voice_lines_land_on_the_right_action():
    expected = {
        "scan my pc": "scan",
        "can you scan my pc": "scan",
        "please scan this computer": "scan",
        "my ram usage is very high": "scan",
        "what's using my memory": "scan",
        "check my ram": "scan",
        "why is my ram so high": "scan",
        "my computer is slow": "scan",
        "free up some memory": "scan",
        "optimize my pc please": "scan",
        "what time is it": "time",
        "what's my vram": "vram",
        "how is my pc": "health",
        "check my email": "mail",
        "remember the cat is called Moth": "remember",
        "search the web for how to scan my computer": "tool-web",
        "who invented dancing": "model",
        "I have a memory of high school": "model",
        "the ram is in the high cabinet": "model",
    }
    misses = {line: route(line) for line, want in expected.items() if route(line) != want}
    assert misses == {}


def test_a_scan_names_a_real_program_instead_of_a_shell_command():
    megabyte = 1024 * 1024
    gigabyte = 1024 ** 3
    heavy = scan(
        [("chrome.exe", 1800 * megabyte, 4), ("notepad.exe", 20 * megabyte, 5)],
        [],
        memory=(20 * gigabyte, 32 * gigabyte),
    )
    speech = heavy.suggestions[0].speech
    assert "chrome.exe" in speech
    assert "Close it?" in speech
    assert heavy.memory_line == "Memory is using 20.0 of 32.0 GB, 62 percent."
    assert "powershell" not in speech.lower()
    assert "voice interface" not in speech.lower()
    assert "powershell" not in heavy.memory_line.lower()

    modest = scan(
        [("chrome.exe", 400 * megabyte, 4)],
        [],
        memory=(8 * gigabyte, 32 * gigabyte),
    )
    assert modest.suggestions == []
    assert modest.summary.startswith("chrome.exe is the heaviest")
    assert "would not close it" in modest.summary
    heard = f"{modest.memory_line} {modest.summary} {speech}"
    assert "Task Manager" not in heard
    assert spoken_reading(20 * gigabyte, 32 * gigabyte, 14).startswith(
        "Memory is using 20.0 of 32.0 GB, 62 percent. CPU is at 14 percent."
    )
    assert memory_sentence(0, 0) == ""


def test_the_spoken_line_is_not_printed_twice():
    spoken, _rest = voice_and_rest(MODEL_REPLY)
    detail = unread_detail(spoken, MODEL_REPLY)
    assert spoken.lower().startswith("i can't actually scan")
    assert not detail.lower().startswith("i can't actually scan")
    assert "voice interface" not in detail.lower()
    assert "Get-Process" in detail
    assert "Task Manager" in detail
    assert "Do not paste shell commands" in system_prompt()
    assert "Do not invent a scan result" in system_prompt()
