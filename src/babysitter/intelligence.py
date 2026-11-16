"""How hard the assistant thinks.

Only one model is loaded at a time. Switching Low, Medium, or High unloads
the model that is in memory before the next one loads.

Low is the fast main model. Medium and High use the writing model. High
holds more of the conversation. A cloud brain, if you turn one on later,
still has to ask before every send. It is not the default.
"""

from __future__ import annotations

from dataclasses import dataclass

from babysitter.vram import LOW_BATCH, LOW_CONTEXT, need_mib


MAIN_MODEL = "qwen3.5:9b"
WRITING_MODEL = "gemma4:12b"
VISION_MODEL = "qwen3-vl:8b"

# Lowest Ollama release past the 2026 security fixes. 0.35.0 closes
# CVE-2026-103663, where a request to the local port can write a file
# outside the model folder and run it. Older than 0.17.1 also has
# CVE-2026-7482, which leaks memory. Both get the same warning.
MIN_OLLAMA_VERSION = (0, 35, 0)


@dataclass(frozen=True)
class IntelligenceMode:
    id: str
    label: str
    summary: str
    model: str
    num_ctx: int
    num_batch: int
    vram_mib: int
    image_edge: int


MODES: dict[str, IntelligenceMode] = {
    "low": IntelligenceMode(
        id="low",
        label="Low",
        summary=(
            "Brief replies. Fastest. Uses qwen3.5:9b for voice, tools, and pictures. "
            "The Q4 file is 5.6 GB, and a normal load is about 6.5 GB once the cache and CUDA are counted."
        ),
        model=MAIN_MODEL,
        num_ctx=LOW_CONTEXT,
        num_batch=LOW_BATCH,
        vram_mib=need_mib(MAIN_MODEL, LOW_CONTEXT),
        image_edge=896,
    ),
    "medium": IntelligenceMode(
        id="medium",
        label="Medium",
        summary=(
            "About 8 to 10 GB of video memory. Uses gemma4:12b for longer writing. "
            "This is the default. Low is the voice model, about 6.5 GB."
        ),
        model=WRITING_MODEL,
        num_ctx=8192,
        num_batch=512,
        vram_mib=need_mib(WRITING_MODEL, 8192),
        image_edge=1280,
    ),
    "high": IntelligenceMode(
        id="high",
        label="High",
        summary=(
            "The writing model with a longer memory. It loads only when the card has room. "
            "A cloud brain is not used unless you turn it on, and it still asks first."
        ),
        model=WRITING_MODEL,
        num_ctx=16384,
        num_batch=512,
        vram_mib=need_mib(WRITING_MODEL, 16384),
        image_edge=1280,
    ),
}


def get_mode(mode_id: str) -> IntelligenceMode:
    return MODES.get(mode_id, MODES["medium"])


def batch_for(model: str, num_ctx: int) -> int:
    """The batch that belongs with this model and context. Every request sends it."""
    for mode in MODES.values():
        if mode.model == model and mode.num_ctx == int(num_ctx):
            return mode.num_batch
    return 512
