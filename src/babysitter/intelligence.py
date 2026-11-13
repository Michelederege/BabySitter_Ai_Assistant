"""How hard the assistant thinks.

Only one model is loaded at a time, and the main model is the one that can
also look at pictures later. Low, Medium, and High do not swap in a second
model. They change how much of the conversation that one model can hold.

A bigger number uses more video memory and can answer with more of the
recent conversation in mind. It is not a different brain.
"""

from __future__ import annotations

from dataclasses import dataclass


MAIN_MODEL = "qwen3.5:9b"
WRITING_MODEL = "gemma4:12b"
VISION_MODEL = "qwen3-vl:8b"

# Lowest Ollama release that includes the fix for CVE-2026-7482.
MIN_OLLAMA_VERSION = (0, 17, 1)


@dataclass(frozen=True)
class IntelligenceMode:
    id: str
    label: str
    summary: str
    model: str
    num_ctx: int


MODES: dict[str, IntelligenceMode] = {
    "low": IntelligenceMode(
        id="low",
        label="Low",
        summary=(
            "Quicker, and lighter on the graphics card. "
            "It holds less of the conversation in mind."
        ),
        model=MAIN_MODEL,
        num_ctx=4096,
    ),
    "medium": IntelligenceMode(
        id="medium",
        label="Medium",
        summary="Everyday balance of speed and memory. This is the default.",
        model=MAIN_MODEL,
        num_ctx=8192,
    ),
    "high": IntelligenceMode(
        id="high",
        label="High",
        summary=(
            "Holds much more of the conversation in mind. "
            "Uses more video memory and the first reply can be slower."
        ),
        model=MAIN_MODEL,
        num_ctx=16384,
    ),
}


def get_mode(mode_id: str) -> IntelligenceMode:
    return MODES.get(mode_id, MODES["medium"])
