"""The microphone switch.

Turning the AI off calls `release`, so every listening path has one place
to stop and hand the microphone back to other programs. Arming marks voice
as permitted without opening the microphone stream until you hold to talk
or turn on keyword listening.
"""

from __future__ import annotations


class AudioGate:
    def __init__(self) -> None:
        self.listening = False
        self.armed = False

    def release(self) -> str:
        self.listening = False
        self.armed = False
        return "The microphone is closed."

    def arm(self) -> str:
        """Allow voice controls while keeping the microphone closed until asked."""
        self.listening = False
        self.armed = True
        return "Voice is ready. The microphone stays closed until you hold to talk or turn on keyword listening."
