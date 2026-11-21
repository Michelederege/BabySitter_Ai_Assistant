"""Hearing: record while Talk is held, then turn it into text on this PC.

The microphone opens only for that hold. The audio stays in memory and is
not saved. Speech recognition runs on the processor, not the graphics card.
Nothing recorded is sent off this computer.
"""

from __future__ import annotations

import io
import re
import sys
import threading
import wave
from dataclasses import dataclass

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


_hearing_model = None
_hearing_lock = threading.Lock()


def load_model():
    """Load the speech model once and keep it until the AI turns off."""
    global _hearing_model
    with _hearing_lock:
        if _hearing_model is None:
            from faster_whisper import WhisperModel

            _hearing_model = WhisperModel(
                "small",
                device="cpu",
                compute_type="int8",
                download_root=str(whisper_dir()),
                cpu_threads=4,
                num_workers=1,
            )
        return _hearing_model


def release_model() -> None:
    """Drop the speech model. The files stay on disk."""
    global _hearing_model
    with _hearing_lock:
        _hearing_model = None


def download_model() -> str:
    """Download the small speech model onto this PC. It is not sent anywhere."""
    if not packages_installed():
        raise HearingError("Install the hearing programs first.")
    load_model()
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

        self.close()
        self._chunks = []

        def on_audio(indata, _frames, _time, status) -> None:
            del status
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


# Command words, so a short line is less often heard as something else.
# One hint only. faster-whisper puts hotwords in this same slot.
COMMAND_HINT = (
    "remind me, set a timer, my goals, find the file, cancel the reminder, "
    "remember that, what time is it."
)


@dataclass(frozen=True)
class Transcript:
    text: str
    confident: bool


def pcm16_to_wav(pcm: bytes, rate: int = 16000) -> bytes:
    """int16 mono samples as a wav the speech model can read."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm or b"")
    return buffer.getvalue()


def hallucinated(text: str) -> bool:
    """A whole line Whisper often invents when the clip is silence."""
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return " ".join(words) in {
        "thanks for watching",
        "thank you for watching",
        "thanks for listening",
        "you",
    }


def _plain(text: str) -> str:
    return " ".join((text or "").lower().split())


def _word_count(text: str) -> int:
    return len(_plain(text).split())


def _matches_local(text: str) -> bool:
    from babysitter.commands import match_quick_command
    from babysitter.intents import match_tool

    heard = (text or "").strip()
    if not heard:
        return False
    return match_quick_command(heard) is not None or match_tool(heard) is not None


def read_speech(wav_bytes: bytes, beam_size: int = 1) -> Transcript:
    """One reading. confident is false when the model itself doubts the line."""
    if not wav_bytes:
        return Transcript("", False)
    if not packages_installed():
        raise HearingError("Speech recognition is not installed yet.")
    if not model_ready():
        raise HearingError(
            "The speech model is not downloaded yet. Open Voice and click Download speech recognition."
        )
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype("float32") / 32768.0
    model = load_model()
    segments, _info = model.transcribe(
        audio,
        language="en",
        beam_size=beam_size,
        vad_filter=True,
        initial_prompt=COMMAND_HINT,
        condition_on_previous_text=False,
    )
    texts: list[str] = []
    logprobs: list[float] = []
    noise: list[float] = []
    for segment in segments:
        texts.append(segment.text.strip())
        logprobs.append(float(segment.avg_logprob))
        noise.append(float(segment.no_speech_prob))
    text = " ".join(part for part in texts if part).strip()
    if not text or not logprobs or hallucinated(text):
        return Transcript("", False)
    average = sum(logprobs) / len(logprobs)
    loud_noise = max(noise) if noise else 0.0
    confident = average >= -1.0 and loud_noise < 0.6
    return Transcript(text, confident)


def needs_second_pass(heard: Transcript) -> bool:
    """A second, slower reading only when the first line is not already a command."""
    if _matches_local(heard.text):
        return False
    return not heard.text or not heard.confident


def pick_pass(first: Transcript, second: Transcript | None) -> Transcript:
    """Prefer a local command, then a confident line, then the first words."""
    if second is not None and _matches_local(second.text):
        return Transcript(second.text, True)
    if _matches_local(first.text) or (first.text and first.confident):
        return first
    if second is not None and second.text and second.confident:
        return second
    if first.text:
        return Transcript(first.text, False)
    if second is not None:
        return Transcript(second.text, False)
    return Transcript("", False)


def merge_lines(vosk: str, whisper: Transcript) -> Transcript:
    """Hands-free keeps the line that is a real command. Whisper wins when it is sure."""
    keyword = (vosk or "").strip()
    heard = Transcript((whisper.text or "").strip(), whisper.confident)
    whisper_matches = _matches_local(heard.text)
    keyword_matches = _matches_local(keyword)
    if whisper_matches and keyword_matches and _plain(heard.text) != _plain(keyword):
        # The hint can make Whisper repeat a short command. The longer line is the request.
        chosen = heard.text if _word_count(heard.text) > _word_count(keyword) else keyword
        return Transcript(chosen, True)
    if whisper_matches and not keyword_matches:
        return Transcript(heard.text, True)
    if keyword_matches and not whisper_matches:
        return Transcript(keyword, True)
    if heard.text and heard.confident:
        return heard
    if keyword:
        return Transcript(keyword, True)
    if heard.text:
        return Transcript(heard.text, False)
    return Transcript("", False)


def transcribe(wav_bytes: bytes) -> str:
    first = read_speech(wav_bytes, beam_size=1)
    second = read_speech(wav_bytes, beam_size=5) if wav_bytes and needs_second_pass(first) else None
    return pick_pass(first, second).text
