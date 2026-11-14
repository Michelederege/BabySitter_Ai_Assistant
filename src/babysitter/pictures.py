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


def room_for_model(free_mib: int | None, model: str) -> str | None:
    """None when the card can hold the model, or when the free amount is unknown."""
    if free_mib is None:
        return None
    need = _need_mib(model)
    if free_mib < need:
        return (
            f"Needs you: not enough video memory. About {free_mib:,} MB is free, "
            f"and {model} needs about {need:,} MB."
        )
    return None


def format_benchmark(samples: list[int]) -> str:
    """Times only. No prompt text and no reply text."""
    if not samples:
        return "No timings."
    shown = ", ".join(f"{int(sample)} ms" for sample in samples)
    return f"Fixed prompt, thinking off, three runs: {shown}."


def _need_mib(model: str) -> int:
    name = model.lower()
    if "gemma" in name:
        return 9000
    if "vl" in name:
        return 9000
    return 8500
