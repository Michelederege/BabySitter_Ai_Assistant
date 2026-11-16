"""Video-memory budget for the Ryzen 9 7900X and RTX 4070 in this PC.

The card reports about 12,282 MB. The desktop and the driver already sit
in that number, so a model only gets what is free. Low still has to answer,
use tools, and look at a shrunk screenshot.

qwen3.5:9b at Q4_K_M is a 5.6 GB weight file. A public config check on
3 November 2026 put a 4,096-token load at about 6.5 GB once the cache and
the CUDA runtime are counted. The old 4 to 6 GB line assumed a 5.4 GB file
and a Qwen3-8B cache. This model is a little larger than that, and its
cache barely shrinks if the context is cut, so Low stays on this file.
Moving layers into system RAM is refused because it makes replies slow.

KV bytes are 2 x layers x kv heads x head size x context x element size.
qwen3.5:9b follows the public Qwen3-8B shape: 36 layers, 8 KV heads, 128.
q4_0 is about 0.28 of fp16. q8_0 is about 0.53. Flash attention has to be
on for either quantized cache, and BabySitter turns it on when it starts
Ollama.
"""

from __future__ import annotations


# nvidia-smi total for a 12 GB RTX 4070, after the usual display reserve.
RTX_4070_TOTAL_MIB = 12282
# A quiet desktop. The real number is read at runtime. This is only for the estimate.
DESKTOP_RESERVE_MIB = 700

QWEN9_LAYERS = 36
QWEN9_KV_HEADS = 8
QWEN9_HEAD_DIM = 128
QWEN9_HIDDEN = 4096
# Q4_K_M weights for qwen3.5:9b. 5.6 GB, from the public file size.
Q4_WEIGHT_MIB = 5734
# CUDA graphs and the runtime that sit with the weights. Counted once,
# so the batch scratch is not added again on top.
RUNTIME_OVERHEAD_MIB = 717

LOW_CONTEXT = 4096
# 256 costs about 36 MB more scratch than 128 and roughly doubles how fast
# a long prompt (a screenshot, a tool reply) is read. Still inside 6 GB.
LOW_BATCH = 256
LOW_CACHE = "q4_0"
LOW_FLOOR_MIB = 4096
# Past this, the load is no longer the Q4 voice model plus its cache.
LOW_CEILING_MIB = 7168

_CACHE_SCALE = {"fp16": 1.0, "q8_0": 0.53, "q4_0": 0.28}


def kv_mib(num_ctx: int, cache: str) -> int:
    """KV cache for qwen3.5:9b at this context and cache type."""
    scale = _CACHE_SCALE.get(cache, _CACHE_SCALE["q8_0"])
    bytes_fp16 = 2 * QWEN9_LAYERS * QWEN9_KV_HEADS * QWEN9_HEAD_DIM * int(num_ctx) * 2
    return max(1, int(bytes_fp16 * scale / (1024 * 1024)))


def scratch_mib(num_batch: int) -> int:
    """One activation slab, plus a small fixed CUDA scratch."""
    slab = int(num_batch) * QWEN9_HIDDEN * QWEN9_LAYERS * 2
    return max(1, int(slab / (1024 * 1024)) + 256)


def low_estimate_mib() -> int:
    """Weights plus the Low cache plus the CUDA runtime."""
    return Q4_WEIGHT_MIB + kv_mib(LOW_CONTEXT, LOW_CACHE) + RUNTIME_OVERHEAD_MIB


def need_mib(model: str, num_ctx: int) -> int:
    """How many free megabytes the card should have before a load."""
    name = (model or "").lower()
    ctx = int(num_ctx)
    if "gemma" in name:
        # Measured near 10 GB at 8,192 on this 12 GB card. A longer context asks for more.
        return 11000 if ctx > 8192 else 9500
    if "vl" in name:
        return 9000
    if ctx <= LOW_CONTEXT:
        estimate = low_estimate_mib()
        return min(LOW_CEILING_MIB, max(LOW_FLOOR_MIB, estimate))
    if ctx >= 16384:
        return 9000
    return 7500


def fits_low_band(used_mib: int) -> bool:
    """True when a finished Low load is still the voice model, not a spill."""
    return LOW_FLOOR_MIB <= int(used_mib) <= LOW_CEILING_MIB


def smaller_context_mib() -> int:
    """What Low would weigh at 2,048 tokens. The weights barely move."""
    return Q4_WEIGHT_MIB + kv_mib(2048, LOW_CACHE) + RUNTIME_OVERHEAD_MIB


def floor_note() -> str:
    """Why Low stays at 4,096 tokens on this card."""
    saved = max(0, low_estimate_mib() - smaller_context_mib())
    return (
        f"Cutting the context from 4,096 to 2,048 would save about {saved} MB "
        "and would clip a screenshot and a tool reply. Low stays at 4,096."
    )


def simulate_ryzen_4070() -> dict:
    """Calculated budget for this PC. It is not a live measurement of the card."""
    working = low_estimate_mib()
    smaller = smaller_context_mib()
    return {
        "card_mib": RTX_4070_TOTAL_MIB,
        "working_mib": working,
        "context_2048_mib": smaller,
        "savings_mib": working - smaller,
        "fits_4_to_6": fits_low_band(working) and working <= 6144,
        "within_voice_budget": working <= LOW_CEILING_MIB,
        "shrinking_context_keeps_features": False,
    }


def low_load_note(name: str, vram_bytes: int, num_ctx: int) -> str | None:
    """A plain sentence after Low loads. Tiny test doubles are ignored."""
    if int(num_ctx) > LOW_CONTEXT or "qwen" not in (name or "").lower():
        return None
    if vram_bytes < 100 * 1024 * 1024:
        return None
    used = int(vram_bytes / (1024 * 1024))
    shown = f"{used / 1024:.1f}"
    if used > LOW_CEILING_MIB:
        return (
            f"Needs you: Low is using about {shown} GB, past 7 GB. "
            "The Q4 voice model is about 5.6 GB before the cache. "
            "BabySitter does not move layers into system memory, because that makes replies slow."
        )
    if fits_low_band(used):
        return (
            f"Low is using about {shown} GB of video memory. "
            "The Q4 file is about 5.6 GB, and the rest is the cache and CUDA."
        )
    return f"Low is using about {shown} GB of video memory."
