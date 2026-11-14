"""Read this PC and suggest one change at a time.

Nothing here runs a shell. A suggestion is applied only after a spoken yes.
Games, Windows itself, and security tools are not closed.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass


HEAVY_BYTES = 700 * 1024 * 1024

PROTECTED_PROCESSES = {
    "system",
    "registry",
    "csrss",
    "lsass",
    "smss",
    "wininit",
    "services",
    "svchost",
    "explorer",
    "dwm",
    "babysitter",
    "ollama",
    "audiodg",
    "securityhealthservice",
    "securityhealthsystray",
    "msmpeng",
    "winlogon",
    "fontdrvhost",
    "sihost",
    "ctfmon",
    "searchhost",
    "startmenuexperiencehost",
    "textinputhost",
    "runtimebroker",
    "dllhost",
    "conhost",
    "idle",
}

PROTECTED_STARTUP = {
    "securityhealth",
    "windowsdefender",
    "window security",
    "riot vanguard",
    "easyanticheat",
}


@dataclass(frozen=True)
class Suggestion:
    kind: str
    speech: str
    name: str
    pid: int = 0
    command: str = ""


@dataclass(frozen=True)
class ScanResult:
    suggestions: list[Suggestion]
    left_games: bool
    summary: str = ""
    memory_line: str = ""


def memory_sentence(used_bytes: int, total_bytes: int) -> str:
    """One spoken sentence for the memory reading. Empty when there is no total."""
    total = int(total_bytes or 0)
    used = max(0, int(used_bytes or 0))
    if total <= 0:
        return ""
    percent = round(100 * used / total)
    used_gb = used / (1024 ** 3)
    total_gb = total / (1024 ** 3)
    return f"Memory is using {used_gb:.1f} of {total_gb:.1f} GB, {percent} percent."


def spoken_reading(used_bytes: int, total_bytes: int, cpu_percent: float | None) -> str:
    """What to say for "how is my pc". The numbers, not a pointer at a tab."""
    line = memory_sentence(used_bytes, total_bytes)
    if cpu_percent is not None:
        line = (line + f" CPU is at {float(cpu_percent):.0f} percent.").strip()
    if not line:
        return "I don't have a memory reading yet. I did not change anything."
    return line + " I did not change anything."


def host_memory() -> tuple[int, int]:
    try:
        import psutil

        memory = psutil.virtual_memory()
        return int(memory.used), int(memory.total)
    except Exception:
        return 0, 0


def _stem(name: str) -> str:
    base = (name or "").strip().lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base


def _plain_name(name: str) -> bool:
    text = (name or "").strip()
    if not text or len(text) > 120:
        return False
    return not any(character in text for character in "\\/:\"")


def _protected_process(name: str) -> bool:
    return _stem(name) in PROTECTED_PROCESSES


def _protected_startup(name: str) -> bool:
    return _stem(name) in PROTECTED_STARTUP


def suggestion_answer(text: str) -> str | None:
    """Yes or no to one suggestion.

    Only a short yes, or deny / skip / leave. "Tell me more" is not a yes,
    because that phrase already means "read the rest of the last answer."
    """
    words = re.findall(r"[a-z']+", (text or "").lower())
    if not words:
        return None
    phrase = " ".join(words)
    if words[0] in {"no", "nope", "nah", "deny", "skip"} or phrase in {
        "leave it",
        "no thanks",
        "no thank you",
    }:
        return "no"
    if phrase in {"go ahead", "do it"}:
        return "yes"
    if words[0] in {"yes", "yeah", "yep", "yup", "sure", "ok", "okay"} and len(words) <= 4:
        return "yes"
    return None


def scan(processes, startups, games=(), memory: tuple[int, int] | None = None) -> ScanResult:
    """Pick at most two heavy apps and one startup item.

    `processes` is (name, rss bytes, pid). `startups` is (name, command).
    Names in `games` are mentioned only by being left alone.
    """
    game_stems = {_stem(name) for name in games}
    suggestions: list[Suggestion] = []
    left_games = False
    ranked = sorted(processes, key=lambda row: int(row[1]), reverse=True)
    heaviest: tuple[str, int] | None = None
    closes = 0
    for name, rss, pid in ranked:
        if not _plain_name(str(name)) or _protected_process(str(name)):
            continue
        if _stem(str(name)) in game_stems:
            left_games = True
            continue
        if heaviest is None:
            heaviest = (str(name), int(rss))
        if closes >= 2:
            continue
        if int(rss) < HEAVY_BYTES:
            continue
        gigabytes = int(rss) / (1024 ** 3)
        suggestions.append(
            Suggestion(
                kind="close_app",
                speech=f"{name} is using {gigabytes:.1f} GB. Close it?",
                name=str(name),
                pid=int(pid),
            )
        )
        closes += 1
    startups_added = 0
    for name, command in list(startups)[:8]:
        if startups_added >= 1:
            break
        if not _plain_name(str(name)) or _protected_startup(str(name)):
            continue
        suggestions.append(
            Suggestion(
                kind="startup",
                speech=f"{name} starts with Windows. Turn that off?",
                name=str(name),
                command=str(command),
            )
        )
        startups_added += 1
    summary = ""
    if closes == 0 and heaviest is not None and heaviest[1] >= 50 * 1024 * 1024:
        gigabytes = heaviest[1] / (1024 ** 3)
        summary = (
            f"{heaviest[0]} is the heaviest I can see, at {gigabytes:.1f} GB. "
            "I would not close it from here."
        )
    used, total = host_memory() if memory is None else (int(memory[0]), int(memory[1]))
    return ScanResult(
        suggestions=suggestions[:3],
        left_games=left_games,
        summary=summary,
        memory_line=memory_sentence(used, total),
    )


def close_named(name: str, *, pids, terminate) -> str:
    """Close every process with this name. `pids` must re-check the live name."""
    if _protected_process(name) or not _plain_name(name):
        return "I left it running. That one stays."
    found = [int(pid) for pid in pids(name)]
    if not found:
        return "It already closed, or it changed. I did not touch it."
    closed = 0
    for pid in found:
        try:
            terminate(pid)
        except Exception:
            continue
        closed += 1
    if closed == 0:
        return "I could not close it. Nothing else was changed."
    if closed == 1:
        return f"Closed {name}."
    return f"Closed {closed} {name} processes."


def pids_named(name: str) -> list[int]:
    import psutil

    want = _stem(name)
    found: list[int] = []
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if _stem(str(proc.info.get("name") or "")) == want:
                found.append(int(proc.info["pid"]))
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    return found


def terminate_pid(pid: int) -> None:
    import psutil

    psutil.Process(int(pid)).terminate()


class DictStartup:
    """A startup list kept in memory. Tests use this. Undo puts the value back."""

    def __init__(self, items: dict[str, str] | None = None) -> None:
        self.items = dict(items or {})

    def disable(self, name: str) -> str:
        if name not in self.items:
            raise KeyError(name)
        return self.items.pop(name)

    def restore(self, name: str, command: str) -> None:
        self.items[name] = command


class WinregStartup:
    """The current user's Run key. Not HKLM, and not a shell command."""

    PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def disable(self, name: str) -> str:
        import winreg

        access = winreg.KEY_READ | winreg.KEY_SET_VALUE
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.PATH, 0, access) as key:
            value, _kind = winreg.QueryValueEx(key, name)
            winreg.DeleteValue(key, name)
        return str(value)

    def restore(self, name: str, command: str) -> None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)


def windows_startup_store():
    if sys.platform != "win32":
        return DictStartup({})
    return WinregStartup()


def apply_startup(suggestion: Suggestion, store) -> tuple[str, str | None]:
    """Turn one startup item off. Returns the speech and the old command for undo."""
    if suggestion.kind != "startup" or _protected_startup(suggestion.name) or not _plain_name(suggestion.name):
        return "I left it. That one stays on.", None
    try:
        previous = store.disable(suggestion.name)
    except Exception:
        return "I could not change that startup item. Nothing else was touched.", None
    speech = (
        f"Turned {suggestion.name} off at startup. "
        "Say undo in the next 10 seconds to put it back."
    )
    return speech, str(previous)


def collect_processes() -> list[tuple[str, int, int]]:
    import psutil

    rows: list[tuple[str, int, int]] = []
    for proc in psutil.process_iter(["name", "memory_info", "pid"]):
        try:
            info = proc.info
            memory = info.get("memory_info")
            rss = int(getattr(memory, "rss", 0) or 0)
            rows.append((str(info.get("name") or ""), rss, int(info.get("pid") or 0)))
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    return rows


def collect_startups() -> list[tuple[str, str]]:
    if sys.platform != "win32":
        return []
    import winreg

    rows: list[tuple[str, str]] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WinregStartup.PATH) as key:
            index = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                rows.append((str(name), str(value)))
                index += 1
    except OSError:
        return []
    return rows
