"""The microphone switch.

Phase 1 does not open the microphone. Turning the AI off still calls
`release`, so the voice code in a later phase has one place to stop
listening and give the microphone back to other programs.
"""

from __future__ import annotations


class AudioGate:
    def __init__(self) -> None:
        self.listening = False
        self.armed = False

    def release(self) -> str:
        self.listening = False
        self.armed = False
        return "Microphone is closed. Voice input is not installed yet."

    def arm(self) -> str:
        """Ready for a later phase. Does not open the microphone."""
        self.listening = False
        self.armed = True
        return "Voice input is not installed yet, so the microphone stays closed."
