"""Hearing: record while Talk is held, then turn it into text on this PC.

The microphone opens only for that hold. The audio stays in memory and is
not saved. Speech recognition runs on the processor, not the graphics card.
Nothing recorded is sent off this computer.
"""

from __future__ import annotations

import io
import sys
import wave

from babysitter.paths import data_dir
from babysitter.platform import run_hidden


HEARING_PACKAGES = ("faster-whisper==1.2.1", "sounddevice==0.5.6")


class HearingError(Exception):
    """The microphone or the speech model could not be used."""


def packages_installed() -> bool:
    try:
        import faster_whisper  # noqa: F401
        import sounddevice  # noqa: F401
    except ImportError:
        return False
    return True


def whisper_dir():
    path = data_dir() / "models" / "whisper"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_ready() -> bool:
    root = whisper_dir()
    return any(root.rglob("*.bin"))


def install_command() -> list[str]:
    return [sys.executable, "-m", "pip", "install", *HEARING_PACKAGES]


def install_packages() -> str:
    """Download the hearing programs. The user must confirm before this runs."""
    completed = run_hidden(install_command(), timeout=900)
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if completed.returncode not in (0, None):
        raise HearingError(output or "The hearing programs did not install.")
    if not packages_installed():
        raise HearingError(
            "The installer finished, but the hearing programs are not available yet. "
            "Close BabySitter, open it again, and try the download once more.\n\n" + output
        )
    return output[-1500:]


def download_model() -> str:
    """Download the small speech model onto this PC. It is not sent anywhere."""
    if not packages_installed():
        raise HearingError("Install the hearing programs first.")
    from faster_whisper import WhisperModel

    WhisperModel("small", device="cpu", compute_type="int8", download_root=str(whisper_dir()))
    if not model_ready():
        raise HearingError("The download finished, but the speech model was not found on this PC.")
    return "Speech recognition is ready. Hold Talk to use it. It runs on the processor, not the graphics card."


class Recorder:
    """Opens the microphone while Talk is held, then closes it."""

    def __init__(self) -> None:
        self._stream = None
        self._chunks: list = []

    def start(self) -> None:
        if not packages_installed():
            raise HearingError("Speech recognition is not installed yet.")
        import sounddevice as sd

        self._chunks = []

        def on_audio(indata, _frames, _time, status) -> None:
            if status:
                return
            self._chunks.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype="float32",
            callback=on_audio,
        )
        self._stream.start()

    def stop(self) -> bytes:
        stream = self._stream
        self._stream = None
        if stream is not None:
            stream.stop()
            stream.close()
        if not self._chunks:
            return b""
        import numpy as np

        audio = np.concatenate(self._chunks)
        self._chunks = []
        pcm = (audio.reshape(-1) * 32767).astype("int16")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(pcm.tobytes())
        return buffer.getvalue()

    def close(self) -> None:
        stream = self._stream
        self._stream = None
        self._chunks = []
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                return


def transcribe(wav_bytes: bytes) -> str:
    if not wav_bytes:
        return ""
    if not packages_installed():
        raise HearingError("Speech recognition is not installed yet.")
    if not model_ready():
        raise HearingError(
            "The speech model is not downloaded yet. Open Voice and click Download speech recognition."
        )
    import numpy as np
    from faster_whisper import WhisperModel

    with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype("float32") / 32768.0
    model = WhisperModel("small", device="cpu", compute_type="int8", download_root=str(whisper_dir()))
    segments, _info = model.transcribe(audio, language="en", vad_filter=True)
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text
