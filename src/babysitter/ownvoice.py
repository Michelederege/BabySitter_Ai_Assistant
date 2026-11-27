"""Your own voice, copied by the natural-voice helper (Chatterbox).

Alex said yes to voice cloning on 27 November 2026, from a recording
of someone who agrees to it. So the only way in is the microphone, after
a consent question each time: there is no "pick a file", which would make
it easy to copy someone who never agreed (a film, a singer, E.D.I.T.H.).

- About 15 seconds of reading a short passage, checked before it is kept:
  not silent, not too quiet, not clipped, at least 6 seconds of speech.
- Saved in the BabySitter folder as models/own-voice/voice.wav, with its
  SHA-256 in own-voice.json. The hash is checked before every use, the
  same rule as every other model file, so a swapped file is refused.
- Never sent anywhere. Delete removes both files.
"""

from __future__ import annotations

import hashlib
import io
import json
import wave
from datetime import datetime
from pathlib import Path

from babysitter.paths import data_dir

OWN_ID = "own"
OWN_NAME = "My voice (recorded on this PC)"
RECORD_SECONDS = 15
MIN_SPEECH_SECONDS = 6.0
MAX_KEEP_SECONDS = 20.0

# Read aloud while recording. Varied sounds and a question and an
# exclamation, so the copy hears how you sound in each.
PASSAGE = (
    "Good morning. The kettle is on, and I have three things to finish today. "
    "First, the reading for class. Then a walk, if the rain holds off. "
    "Did I leave my keys by the door again? Never mind, I found them! "
    "It's quiet outside, the light is soft, and I'm in no hurry at all."
)

CONSENT = (
    "BabySitter will copy how you sound from about 15 seconds of you reading a short passage.\n\n"
    "Only record your own voice, or the voice of someone who is with you and agrees to it. "
    "Don't play a recording of anyone else into the microphone.\n\n"
    "The recording stays on this PC, in your BabySitter folder, and is never sent anywhere. "
    "You can delete it at any time on the Voice page. Speaking in your voice needs the natural voices "
    "set up, and it uses the graphics card like the narrators do."
)


class OwnVoiceError(Exception):
    """The recording could not be used. The message says what to do."""


def folder() -> Path:
    return data_dir() / "models" / "own-voice"


def clip_path() -> Path:
    return folder() / "voice.wav"


def record_path() -> Path:
    return folder() / "own-voice.json"


def _record() -> dict:
    try:
        data = json.loads(record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def ready() -> bool:
    return clip_path().is_file() and bool(_record().get("sha256"))


def verified_clip() -> Path:
    """The clip, after checking it is the one you recorded."""
    path = clip_path()
    expected = str(_record().get("sha256") or "")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise OwnVoiceError("Your voice is not recorded yet. Record it on the Voice page.") from exc
    if not expected or hashlib.sha256(data).hexdigest() != expected:
        raise OwnVoiceError("Your voice recording was changed since you made it, so it was not used. Record it again.")
    return path


def delete() -> str:
    removed = False
    for path in (clip_path(), record_path()):
        try:
            path.unlink()
            removed = True
        except FileNotFoundError:
            pass
    return "Your voice recording is deleted from this PC." if removed else "There was no voice recording to delete."


# ---- Checking a take -----------------------------------------------------

def _frames_rms(samples, rate: int, frame_ms: int = 20):
    import numpy as np

    size = max(1, int(rate * frame_ms / 1000))
    usable = len(samples) // size * size
    if usable == 0:
        return np.zeros(0, dtype=np.float32), size
    frames = samples[:usable].reshape(-1, size)
    return np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)), size


def check_take(samples, rate: int):
    """Trim the take to the speech and judge it. Returns (trimmed samples, None) or (None, why not)."""
    import numpy as np

    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    if samples.size == 0 or float(np.max(np.abs(samples))) < 1e-4:
        return None, "The microphone sent silence. Pick the microphone you talk into in Settings, then try again."
    clipped = float(np.mean(np.abs(samples) >= 0.99))
    if clipped > 0.005:
        return None, "That was too loud and the sound broke up. Sit a little further from the microphone and try again."
    rms, size = _frames_rms(samples, rate)
    loudest = float(np.percentile(rms, 95)) if rms.size else 0.0
    if loudest < 0.01:
        return None, "That was too quiet to copy. Move closer to the microphone, or speak up a little, and try again."
    speaking = rms > max(0.004, loudest * 0.12)
    speech_seconds = float(np.sum(speaking)) * size / rate
    if speech_seconds < MIN_SPEECH_SECONDS:
        return None, (f"I heard about {speech_seconds:.0f} seconds of speech and need at least {MIN_SPEECH_SECONDS:.0f}. "
                      "Read the whole passage, then try again.")
    # Keep from a little before the first spoken frame to a little after the last.
    where = np.flatnonzero(speaking)
    pad = int(0.15 * rate)
    start = max(0, where[0] * size - pad)
    end = min(samples.size, (where[-1] + 1) * size + pad)
    end = min(end, start + int(MAX_KEEP_SECONDS * rate))
    return samples[start:end], None


def wav_bytes(samples, rate: int) -> bytes:
    import numpy as np

    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(int(rate))
        out.writeframes(pcm)
    return buffer.getvalue()


def save(samples, rate: int) -> str:
    """Keep a checked take. The caller must have asked for consent first."""
    trimmed, problem = check_take(samples, rate)
    if problem:
        raise OwnVoiceError(problem)
    data = wav_bytes(trimmed, rate)
    folder().mkdir(parents=True, exist_ok=True)
    temporary = clip_path().with_suffix(".part")
    temporary.write_bytes(data)
    temporary.replace(clip_path())
    record = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "seconds": round(len(trimmed) / rate, 1),
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "consent": "Recorded through the microphone after the consent question: the speaker's own voice, or a present speaker who agreed.",
    }
    record_path().write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return f"Your voice is saved on this PC ({record['seconds']:.0f} seconds). Choose “{OWN_NAME}” and press Use this voice."


def record(seconds: int = RECORD_SECONDS, device: int | None = None, stop=None):
    """Record from the chosen microphone. Returns (float32 samples, rate). `stop` ends it early."""
    import numpy as np
    import sounddevice as sd

    try:
        info = sd.query_devices(device, "input")
        rate = int(info.get("default_samplerate") or 48000)
    except Exception:  # noqa: BLE001 - fall back to a rate every Windows microphone accepts
        rate = 48000
    chunks: list = []

    def take(indata, _frames, _time, _status) -> None:
        chunks.append(indata[:, 0].copy())

    import time

    with sd.InputStream(samplerate=rate, channels=1, dtype="float32", device=device, callback=take):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if stop is not None and stop.is_set():
                break
            time.sleep(0.05)
    samples = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    return samples, rate
