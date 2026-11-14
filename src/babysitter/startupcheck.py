"""Checks Ollama's version once, when the window opens.

Older than 0.35.0 is CVE-2026-103663: a program that can reach Ollama's
local port can make it write a file outside its model folder, and that
file runs the next time Ollama starts. Older than 0.17.1 also has
CVE-2026-7482, where a crafted model file leaks what Ollama has in memory.
"""

from __future__ import annotations

from dataclasses import dataclass

from babysitter.intelligence import MIN_OLLAMA_VERSION
from babysitter.ollama import OllamaClient, parse_ollama_version, version_is_older


@dataclass(frozen=True)
class VersionReport:
    found: bool
    version: tuple[int, int, int] | None
    raw: str
    older: bool
    message: str
    tray_running: bool


def version_message(found: tuple[int, int, int] | None, raw: str, missing: str | None) -> tuple[bool, bool, str]:
    """Return (command_found, older_than_safe, plain message)."""
    if missing:
        return False, False, missing
    if found is None:
        shown = (raw or "no text").strip()[:240]
        return True, True, (
            "I could not read the Ollama version, so I'm treating it as too old. "
            f"It said: {shown}"
        )
    dotted = ".".join(str(part) for part in found)
    if version_is_older(found, MIN_OLLAMA_VERSION):
        safe = ".".join(str(part) for part in MIN_OLLAMA_VERSION)
        return True, True, (
            f"Ollama {dotted} is older than {safe}. "
            "Anything older has a critical security flaw (CVE-2026-103663): "
            "a program on this PC can make Ollama write a file outside its "
            "model folder and run it. Update Ollama itself before you turn "
            "the AI on. ollama pull only refreshes models, not the engine. "
            "The download page is https://ollama.com/download"
        )
    return True, False, f"Ollama {dotted} is new enough."


def check_ollama(ollama: OllamaClient) -> VersionReport:
    raw, missing = ollama.read_version_text()
    parsed = parse_ollama_version(raw) if not missing else None
    found, older, message = version_message(parsed, raw, missing)
    try:
        tray = bool(ollama.tray_names())
    except OSError:
        tray = False
    return VersionReport(
        found=found,
        version=parsed,
        raw=raw,
        older=older,
        message=message,
        tray_running=tray,
    )
