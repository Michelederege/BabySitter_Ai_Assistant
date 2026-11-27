"""Filler lines that are already audio, not spoken live.

The three lines are rendered once, while no voice turn is open, and saved
as wav files in the personal folder. During a reply BabySitter plays the
file. It does not run the voice engine for "One moment."
"""

from __future__ import annotations

import threading
import wave
from pathlib import Path

from babysitter.paths import data_dir
from babysitter.plugins.voice.playback import play_pcm_blocks


PHRASES = ("One moment.", "Still working.", "Give me a second.")


def filler_dir() -> Path:
    path = data_dir() / "fillers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _wav_path(folder: Path, index: int) -> Path:
    return folder / f"{index}.wav"


def write_wav(path: Path, pcm: bytes, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(pcm)


def read_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        pcm = handle.readframes(handle.getnframes())
    return pcm, rate


class FillerLibrary:
    def __init__(self, folder: Path | None = None) -> None:
        self.folder = folder

    def _folder(self) -> Path:
        return self.folder if self.folder is not None else filler_dir()

    def ready(self) -> bool:
        folder = self._folder()
        return all(_wav_path(folder, index).is_file() for index in range(len(PHRASES)))

    def prepare(self, render, busy) -> str:
        """Render any missing clip. Skips the rest of the work if a turn is open.

        render(text) returns (int16 pcm bytes, sample rate).
        """
        if busy():
            return "skipped"
        folder = self._folder()
        wrote = False
        for index, phrase in enumerate(PHRASES):
            if busy():
                return "skipped"
            path = _wav_path(folder, index)
            if path.is_file() and path.stat().st_size > 44:
                continue
            pcm, rate = render(phrase)
            if not pcm:
                continue
            write_wav(path, pcm, rate)
            wrote = True
        if self.ready():
            return "ready" if wrote else "cached"
        return "incomplete"

    def clip(self, index: int) -> tuple[bytes, int] | None:
        path = _wav_path(self._folder(), index % len(PHRASES))
        if not path.is_file():
            return None
        try:
            return read_wav(path)
        except (OSError, wave.Error):
            return None


def library(voice_name: str = "") -> FillerLibrary:
    """The clips for one voice. "One moment." in Heart and Sarah used to play
    in front of every voice, so each voice now has its own three clips."""
    import re

    name = (voice_name or "").strip()
    if not name or name == "Heart & Sarah blend":
        return FillerLibrary()  # the clips already saved before voices had folders
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "voice"
    return FillerLibrary(filler_dir() / slug)


def play_clip(pcm: bytes, rate: int, stop_event: threading.Event) -> bool:
    """Play one clip in short blocks. False if it was stopped or audio is missing."""
    try:
        import sounddevice as sd
    except (ImportError, OSError):
        return False
    import array

    samples = array.array("h")
    samples.frombytes(pcm)
    try:
        with sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16") as stream:
            return play_pcm_blocks(samples, rate, stop_event, stream.write, publish=None)
    except Exception:
        return False
