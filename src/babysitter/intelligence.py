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


# Timed on the Models page only. About twice this card's video memory, so
# it spills into system memory and cannot be a level while every layer has
# to stay on the graphics card.
BENCHMARK_ONLY = ("bonsai-2:27b",)

# The memory slider. Low, Medium, and High stay the three loads that fit
# the card; the slider adds stops between them. Each stop belongs to the
# level whose model it uses, so a stop never loads a model that does not
# fit. 0 means "the level's own amount".
CONTEXT_STOPS = (4096, 6144, 8192, 12288, 16384)
_context = {"tokens": 0}


def level_for_context(tokens: int) -> str:
    if int(tokens) <= MODES["low"].num_ctx:
        return "low"
    if int(tokens) <= MODES["medium"].num_ctx:
        return "medium"
    return "high"


def set_context(tokens: int) -> int:
    """Use this many tokens of conversation. Anything off the stops means the level's default."""
    value = int(tokens or 0)
    _context["tokens"] = value if value in CONTEXT_STOPS else 0
    return _context["tokens"]


def get_mode(mode_id: str) -> IntelligenceMode:
    """The level, with the slider's amount of conversation when it belongs to this level.

    Every caller sees the same numbers, so a question always asks for the
    context that is loaded. A different number makes Ollama load again.
    """
    from dataclasses import replace

    base = MODES.get(mode_id, MODES["medium"])
    tokens = _context["tokens"]
    if tokens and level_for_context(tokens) == base.id and tokens != base.num_ctx:
        return replace(base, num_ctx=tokens, vram_mib=need_mib(base.model, tokens))
    return base


def batch_for(model: str, num_ctx: int) -> int:
    """The batch that belongs with this model and context. Every request sends it."""
    for mode in MODES.values():
        if mode.model == model and mode.num_ctx == int(num_ctx):
            return mode.num_batch
    return 512
