"""Shrink a screenshot before it is shown to the model."""

from __future__ import annotations


def scaled_size(width: int, height: int, limit: int = 1280) -> tuple[int, int]:
    """Keep the long edge at or under the limit. Native size is kept when it already fits."""
    width = max(0, int(width))
    height = max(0, int(height))
    long_edge = max(width, height)
    if long_edge <= limit or long_edge == 0:
        return width, height
    scale = limit / long_edge
    return max(1, int(width * scale)), max(1, int(height * scale))


def room_for_model(free_mib: int | None, model: str, num_ctx: int = 8192) -> str | None:
    """None when the card can hold the model, or when the free amount is unknown."""
    if free_mib is None:
        return None
    need = _need_mib(model, num_ctx)
    if free_mib < need:
        return (
            f"Needs you: not enough video memory. About {free_mib:,} MB is free, "
            f"and {model} needs about {need:,} MB."
        )
    return None


def image_tokens(width: int, height: int) -> int:
    """Qwen counts one image token per 32 by 32 patch. This is an estimate."""
    width = max(0, int(width))
    height = max(0, int(height))
    if width == 0 or height == 0:
        return 0
    return max(1, (width * height) // (32 * 32))


def format_benchmark(samples: list) -> str:
    """Times and speeds only. No prompt text and no reply text."""
    if not samples:
        return "No timings."
    lines = ["Fixed prompt, thinking off."]
    for index, sample in enumerate(samples, start=1):
        if isinstance(sample, int) and not isinstance(sample, bool):
            lines.append(f"Run {index}: {sample} ms.")
            continue
        if not isinstance(sample, dict):
            continue
        bits = []
        if "load_ms" in sample:
            bits.append(f"load {int(sample['load_ms'])} ms")
        if "prompt_tps" in sample:
            bits.append(f"prompt {int(sample['prompt_tps'])} tokens/s")
        if "gen_tps" in sample:
            bits.append(f"generation {int(sample['gen_tps'])} tokens/s")
        if "wall_ms" in sample and "gen_tps" not in sample:
            bits.append(f"{int(sample['wall_ms'])} ms")
        if bits:
            lines.append(f"Run {index}: " + ", ".join(bits) + ".")
    return " ".join(lines)


def benchmark_warning(current_tps: int, baseline_tps: int) -> str | None:
    """Warn when generation is more than about 20% slower than a saved run."""
    if current_tps <= 0 or baseline_tps <= 0:
        return None
    if current_tps < int(baseline_tps * 0.8):
        return (
            f"Generation is slower than the saved baseline "
            f"({current_tps} vs {baseline_tps} tokens per second)."
        )
    return None


def _need_mib(model: str, num_ctx: int) -> int:
    name = model.lower()
    if "gemma" in name:
        # Measured near 10 GB at 8K on a 12 GB card. A longer context asks for more.
        return 11000 if int(num_ctx) > 8192 else 9500
    if "vl" in name:
        return 9000
    return 9000 if int(num_ctx) >= 16384 else 8500
