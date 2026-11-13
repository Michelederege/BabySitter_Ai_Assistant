"""How hard the assistant thinks.

Only one model is loaded at a time. Switching Low, Medium, or High unloads
the model that is in memory before the next one loads.

Low is the fast main model. Medium and High use the writing model. High
holds more of the conversation. A cloud brain, if you turn one on later,
still has to ask before every send. It is not the default.
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
        summary="Brief replies. Fastest. Uses qwen3.5:9b, which can also look at pictures.",
        model=MAIN_MODEL,
        num_ctx=4096,
    ),
    "medium": IntelligenceMode(
        id="medium",
        label="Medium",
        summary="Everyday answers, including writing. Uses gemma4:12b. This is the default.",
        model=WRITING_MODEL,
        num_ctx=8192,
    ),
    "high": IntelligenceMode(
        id="high",
        label="High",
        summary=(
            "The writing model with a longer memory. Uses more video memory. "
            "A cloud brain is not used unless you turn it on, and it still asks first."
        ),
        model=WRITING_MODEL,
        num_ctx=16384,
    ),
}


def get_mode(mode_id: str) -> IntelligenceMode:
    return MODES.get(mode_id, MODES["medium"])
