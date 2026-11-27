"""Turn-taking extras. All of them stay off until a setting says otherwise.

Silero is used when its onnx file is already on this PC and onnxruntime
imports. Otherwise the energy check does the same job on the processor.
Neither one is downloaded from here, and neither one uses the graphics card.

Smart Turn lengthens the pause after a short utterance and shortens it
after a longer one. Echo cancellation subtracts the audio BabySitter just
played. Talk-over only counts when that subtraction actually ran, so the
assistant's own voice cannot interrupt it.
"""

from __future__ import annotations

import array
from pathlib import Path


SPEECH_RMS = 500


def rms(pcm: bytes) -> float:
    """Loudness of int16 audio. numpy, since the keyword loop calls this 20 times a second."""
    if not pcm:
        return 0.0
    try:
        import numpy as np
    except ImportError:
        return _rms_plain(pcm)
    samples = np.frombuffer(pcm[: len(pcm) - (len(pcm) % 2)], dtype="<i2")
    if not samples.size:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def _rms_plain(pcm: bytes) -> float:
    samples = array.array("h")
    usable = pcm[: len(pcm) - (len(pcm) % 2)]
    if not usable:
        return 0.0
    samples.frombytes(usable)
    if not samples:
        return 0.0
    total = sum(int(sample) * int(sample) for sample in samples)
    return (total / len(samples)) ** 0.5


def is_speech(pcm: bytes, threshold: float = SPEECH_RMS) -> bool:
    return rms(pcm) >= threshold


def residual_pcm(mic: bytes, playback: bytes) -> bytes:
    """Subtract playback from the microphone. Length follows the microphone."""
    try:
        import numpy as np
    except ImportError:
        return _residual_plain(mic, playback)
    mic_samples = np.frombuffer(mic[: len(mic) - (len(mic) % 2)], dtype="<i2").astype(np.int32)
    play = np.frombuffer(playback[: len(playback) - (len(playback) % 2)], dtype="<i2")
    count = min(len(play), len(mic_samples))
    mic_samples[:count] -= play[:count]
    return np.clip(mic_samples, -32768, 32767).astype("<i2").tobytes()


def _residual_plain(mic: bytes, playback: bytes) -> bytes:
    mic_samples = array.array("h")
    play_samples = array.array("h")
    mic_bytes = mic[: len(mic) - (len(mic) % 2)]
    play_bytes = playback[: len(playback) - (len(playback) % 2)]
    if mic_bytes:
        mic_samples.frombytes(mic_bytes)
    if play_bytes:
        play_samples.frombytes(play_bytes)
    mixed = array.array("h")
    for index, sample in enumerate(mic_samples):
        other = play_samples[index] if index < len(play_samples) else 0
        mixed.append(max(-32768, min(32767, int(sample) - int(other))))
    return mixed.tobytes()


def prepare_chunk(chunk: bytes, echo_cancel: bool, playback: bytes) -> tuple[bytes, bool]:
    """Return the chunk to recognize, and whether echo cancellation ran."""
    if not echo_cancel or len(playback) < 2:
        return chunk, False
    return residual_pcm(chunk, playback), True


def barge_in(energy: float, echo_applied: bool, talk_over: bool, hot: int, threshold: float = SPEECH_RMS) -> tuple[bool, int]:
    """Count loud residual frames. Talk-over needs the echo path to have run."""
    if not talk_over or not echo_applied:
        return False, 0
    if energy >= threshold:
        hot += 1
    else:
        hot = 0
    return hot >= 3, hot


def endpoint_delays(smart_turn: bool, heard_words: int) -> tuple[float, float, float] | None:
    """Vosk endpointer delays, or None to keep the listener's own defaults.

    The middle number is seconds of quiet that end the turn.
    """
    if not smart_turn:
        return None
    if heard_words >= 8:
        return (5.0, 0.28, 12.0)
    return (5.0, 0.55, 12.0)


def finished_by_silence(quiet_chunks: int, heard_words: int, smart_turn: bool, vad_enabled: bool) -> bool:
    """True when enabled listening should stop waiting."""
    if not vad_enabled and not smart_turn:
        return False
    if heard_words <= 0:
        return False
    need = 2 if smart_turn and heard_words >= 8 else 4 if smart_turn else 5
    return quiet_chunks >= need


class EnergyVad:
    """The processor stand-in used when Silero's file is not on this PC."""

    id = "energy"

    def speech(self, pcm: bytes) -> bool:
        return is_speech(pcm)


class SileroVad:
    """Calls a session that already wraps the Silero onnx model.

    The session only needs speech(pcm) -> bool. Loading the file is separate
    so tests never touch onnxruntime.
    """

    id = "silero"

    def __init__(self, session) -> None:
        self._session = session

    def speech(self, pcm: bytes) -> bool:
        return bool(self._session.speech(pcm))


def open_vad(enabled: bool, model_path: Path | None = None):
    """None when the feature is off. Silero when the file and runtime exist."""
    if not enabled:
        return None
    path = model_path
    if path is not None and path.is_file():
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            return EnergyVad()
        session = _silero_session(path)
        if session is not None:
            return SileroVad(session)
    return EnergyVad()


def _silero_session(path: Path):
    try:
        import onnxruntime as ort
    except ImportError:
        return None

    class _Session:
        def __init__(self, model: Path) -> None:
            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            self._session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
            self._state = None
            self._sr = None

        def speech(self, pcm: bytes) -> bool:
            # A missing or unexpected model falls back to energy rather than crashing the mic.
            try:
                return _silero_speech(self, pcm)
            except Exception:
                return is_speech(pcm)

    try:
        return _Session(path)
    except Exception:
        return None


def _silero_speech(holder, pcm: bytes) -> bool:
    """One 512-sample Silero frame. Extra samples are ignored."""
    import array

    import numpy as np

    samples = array.array("h")
    usable = pcm[: len(pcm) - (len(pcm) % 2)]
    if not usable:
        return False
    samples.frombytes(usable)
    frame = np.zeros(512, dtype=np.float32)
    count = min(512, len(samples))
    if count:
        frame[:count] = np.array(samples[:count], dtype=np.float32) / 32768.0
    session = holder._session
    inputs = {item.name: None for item in session.get_inputs()}
    names = list(inputs)
    feed = {}
    # Common Silero v5 input names: input, state, sr.
    for name in names:
        if "input" in name or name in {"input", "x"}:
            feed[name] = frame.reshape(1, -1)
        elif "sr" in name:
            feed[name] = np.array(16000, dtype=np.int64)
        elif "state" in name:
            if holder._state is None:
                shape = [dim if isinstance(dim, int) and dim > 0 else 1 for dim in session.get_inputs()[names.index(name)].shape]
                holder._state = np.zeros(shape, dtype=np.float32)
            feed[name] = holder._state
        else:
            feed[name] = frame.reshape(1, -1)
    outputs = session.run(None, feed)
    if len(outputs) >= 2:
        holder._state = outputs[1]
    score = float(np.array(outputs[0]).reshape(-1)[0])
    return score >= 0.5
