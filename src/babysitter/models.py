"""Which model does which job.

Low is the voice, the tools, mail, calendar, and a shrunk screenshot.
Medium and High are the writing model, and only when the card is free.
A second model is not loaded beside the first.
"""

from babysitter.vram import floor_note


def model_choice() -> str:
    """The decision for this PC, in plain sentences."""
    return (
        "Low stays on qwen3.5:9b. That is the smallest model here that still follows "
        "a tool, a calendar, and a short talk. A 3B or 4B model would use less video "
        "memory and would miss those. gemma4:12b is for longer writing, and only when "
        "the card is free. Only one model is loaded. " + floor_note()
    )
