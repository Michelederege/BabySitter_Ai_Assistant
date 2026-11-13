"""The shape every voice engine has to follow.

A new engine (a local voice, a Windows voice, a cloud voice) is a new file
in this folder. The rest of the app should only talk to these methods.

Voice cloning is not one of the engines and will not be added.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VoiceInfo:
    engine_id: str
    voice_id: str
    label: str
    accent: str  # "American", "British", "Australian", or another plain word


class VoiceOutput(Protocol):
    """Speaks text. Phase 1 does not ship an engine."""

    id: str
    label: str

    def list_voices(self) -> list[VoiceInfo]:
        """Voices this engine can speak with."""

    def speak(self, text: str, voice_id: str, speed: float, pitch: float) -> None:
        """Say this text. Text should already be written for speech."""

    def stop(self) -> None:
        """Stop speaking immediately, including if the user interrupts."""


class VoiceInput(Protocol):
    """Records while a key is held. Phase 1 does not open the microphone."""

    def start(self) -> None:
        """Begin recording from the chosen microphone."""

    def stop(self) -> bytes:
        """Stop and return the audio that was recorded."""

    def close(self) -> None:
        """Release the microphone so other programs can use it."""
