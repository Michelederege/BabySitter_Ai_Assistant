"""One-tap fixes: the problem BabySitter just reported, and the one button that fixes it.

Each problem message the app already writes is matched to a fix. The fix is
a key the window turns into an action. Nothing here acts by itself: a fix
runs only when the button is pressed, or when he says or types "fix it",
and a download still asks its own yes first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OLLAMA_PAGE = "https://ollama.com/download"


@dataclass(frozen=True)
class Fix:
    """What the notice says, what its button says, and the action key."""

    text: str
    button: str
    action: str


# Settings sections a fix may open. The same keys as the window's section list.
SECTIONS = {"voice", "brain", "personality", "games", "accounts", "alerts", "privacy", "this_pc", "updates"}

_MODEL_MISSING = re.compile(r"The model (\S+) is not downloaded")


def fix_for(message: str, *, level: str = "") -> Fix | None:
    """The fix for one problem message, or None when there is no single fix."""
    text = " ".join((message or "").split())
    lowered = text.lower()
    if not lowered:
        return None
    if "ollama is not installed" in lowered or "cannot find ollama.exe" in lowered:
        return Fix(
            "Ollama isn't installed, so the AI can't start.",
            "Get Ollama",
            "open_ollama_page",
        )
    if "listening on the whole network" in lowered:
        return Fix(
            "Ollama is open to other computers on the network, so BabySitter didn't use it.",
            "Restart it privately",
            "restart_ollama",
        )
    found = _MODEL_MISSING.search(text)
    if found:
        model = found.group(1).rstrip(".,")
        return Fix(f"{model} isn't downloaded yet.", "Download it", "pull_model:" + model)
    if "not enough video memory" in lowered:
        if level and level != "low":
            return Fix(
                "There isn't room on the graphics card for this level.",
                "Use Low instead",
                "use_low",
            )
        return Fix(
            "There isn't room on the graphics card. A game or another app may be using it.",
            "Try again",
            "retry",
        )
    if "did not answer at 127.0.0.1" in lowered or "could not reach ollama" in lowered or "took too long" in lowered:
        return Fix("Ollama didn't answer.", "Try again", "retry")
    if lowered.startswith("quiet hours are"):
        return Fix("Quiet hours are on, so the AI stays off.", "Turn quiet hours off", "quiet_off")
    if "web search is off" in lowered:
        return Fix("Web search is off.", "Set up web search", "settings:accounts")
    if "google is off" in lowered or "google is not signed in" in lowered:
        return Fix("Google isn't connected.", "Connect Google", "settings:accounts")
    if "home assistant token" in lowered:
        return Fix("Home Assistant isn't connected.", "Connect it", "settings:accounts")
    if "download speech recognition" in lowered:
        return Fix("Speech recognition isn't on this PC yet.", "Download it", "get_hearing")
    if "sending silence" in lowered or "no sound came from" in lowered or "no sound is coming from" in lowered:
        return Fix("The microphone is sending silence.", "Pick a microphone", "settings:voice")
    if "is not downloaded yet. download it on the voice tab" in lowered:
        return Fix("That voice isn't downloaded yet.", "Open Voice", "settings:voice")
    if "turn the detector on in settings" in lowered or "turn it on in settings" in lowered:
        return Fix("The sharper voice detector is downloaded but off.", "Turn it on", "silero_on")
    return None


# Said or typed while a fix is showing.
_FIX_WORDS = re.compile(r"^(?:ok(?:ay)?,? |yes,? |please,? )?(?:fix (?:it|that|this)|do that|go ahead and fix it)(?: please)?[.!]?$")


def asks_for_the_fix(line: str) -> bool:
    """True for "fix it", "yes fix it", "fix that please"."""
    return bool(_FIX_WORDS.match(" ".join((line or "").lower().split())))


def section_of(action: str) -> str:
    """The settings section of a "settings:…" action, or ""."""
    if not action.startswith("settings:"):
        return ""
    key = action.split(":", 1)[1]
    return key if key in SECTIONS else ""
