"""The extra hearing engines and voices, all on the processor.

Hearing: Whisper stays the default. Moonshine is the fast choice and
Parakeet the accurate one. Only the chosen engine is loaded, and only one
hears the question; Vosk still only listens for the keyword.

Voices: Kokoro stays the default. Piper and Supertonic are other voices.
Each renders a sentence to audio, and the same player says it, so echo
cancellation and talk-over stay in front of whichever voice is chosen.
The Windows voice is the fallback when a model file is missing.

Each engine is loaded the first time it is used and kept until the AI
turns off, so a choice that is not in use costs nothing.
"""

from __future__ import annotations

import io
import re
import threading
import wave

from babysitter.modelpacks import PACKS, PackError, find, ready, verify

HEARING_ENGINES = {
    "whisper": "Whisper (default)",
    "moonshine": PACKS["moonshine"].label,
    "parakeet": PACKS["parakeet"].label,
}

# Shown on the Voice tab. The value is (pack id, speaker or style).
EXTRA_VOICES = {
    "Piper: HFC female": ("piper-hfc", ""),
    "Piper: Jenny (British)": ("piper-jenny", ""),
    "Supertonic: F1": ("supertonic", "F1"),
    "Supertonic: F2": ("supertonic", "F2"),
    "Supertonic: F3": ("supertonic", "F3"),
    "Supertonic: M1": ("supertonic", "M1"),
}

_lock = threading.Lock()
_loaded: dict[str, object] = {}


class EngineError(Exception):
    """An extra engine could not be used. The message says what to do."""


def release() -> None:
    """Drop every loaded engine. The files stay on disk."""
    with _lock:
        _loaded.clear()


def _threads() -> int:
    return 4


# ---- Hearing -------------------------------------------------------------

def _recognizer(engine: str):
    import sherpa_onnx as so

    try:
        folder = verify(engine)
    except PackError as exc:
        raise EngineError(str(exc)) from None
    if engine == "moonshine":
        return so.OfflineRecognizer.from_moonshine_v2(
            encoder=str(find(folder, "encoder_model.ort")),
            decoder=str(find(folder, "decoder_model_merged.ort")),
            tokens=str(find(folder, "tokens.txt")),
            num_threads=_threads(),
        )
    if engine == "parakeet":
        return so.OfflineRecognizer.from_transducer(
            encoder=str(find(folder, "encoder*.onnx")),
            decoder=str(find(folder, "decoder*.onnx")),
            joiner=str(find(folder, "joiner*.onnx")),
            tokens=str(find(folder, "tokens.txt")),
            num_threads=_threads(),
            model_type="nemo_transducer",
        )
    raise EngineError(f"Unknown hearing engine {engine}.")


def _samples(wav: bytes):
    import numpy as np

    with wave.open(io.BytesIO(wav), "rb") as handle:
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
        channels = handle.getnchannels()
    audio = np.frombuffer(frames, dtype=np.int16).astype("float32") / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, rate


def hear(engine: str, wav: bytes) -> str:
    """The words in one recording, with the chosen engine."""
    if engine not in {"moonshine", "parakeet"}:
        raise EngineError("Whisper is read by the speech module.")
    if not ready(engine):
        raise EngineError(f"{PACKS[engine].label} is not downloaded yet. Download it on the Voice tab.")
    with _lock:
        recognizer = _loaded.get(engine)
        if recognizer is None:
            recognizer = _recognizer(engine)
            _loaded[engine] = recognizer
    audio, rate = _samples(wav)
    stream = recognizer.create_stream()
    stream.accept_waveform(rate, audio)
    recognizer.decode_stream(stream)
    words = " ".join((stream.result.text or "").split())
    # Moonshine and Parakeet can write "six thirty" as 6.30. The reminder
    # words expect 6:30. Only after a time word, so 3.14 stays a number.
    return re.sub(r"\b(at|by|until|till|from|around|before|after)\s+(\d{1,2})\.(\d{2})\b", r"\1 \2:\3", words, flags=re.IGNORECASE)


# ---- Voices --------------------------------------------------------------

def voice_ready(name: str) -> bool:
    pack = EXTRA_VOICES.get(name)
    return pack is not None and ready(pack[0])


def _piper(pack_id: str):
    """Piper's own package. It carries the espeak step that turns words into
    sounds; the sherpa-onnx 2.0 Windows build no longer includes it."""
    from piper import PiperVoice

    try:
        folder = verify(pack_id)
    except PackError as exc:
        raise EngineError(str(exc)) from None
    model = find(folder, "*.onnx")
    return PiperVoice.load(model, config_path=model.with_name(model.name + ".json"))


def _supertonic():
    from supertonic import TTS

    try:
        folder = verify("supertonic")
    except PackError as exc:
        raise EngineError(str(exc)) from None
    # auto_download stays off: the files came through the confirmed, checked download.
    return TTS(model="supertonic-3", model_dir=str(folder), auto_download=False, intra_op_num_threads=_threads())


def render(name: str, text: str, speed: float = 1.0):
    """One sentence as (float32 samples, sample rate) in an extra voice."""
    pack = EXTRA_VOICES.get(name)
    if pack is None:
        raise EngineError(f"Unknown voice {name}.")
    pack_id, style = pack
    if not ready(pack_id):
        raise EngineError(f"{PACKS[pack_id].label} is not downloaded yet. Download it on the Voice tab.")
    with _lock:
        engine = _loaded.get(pack_id)
        if engine is None:
            engine = _supertonic() if pack_id == "supertonic" else _piper(pack_id)
            _loaded[pack_id] = engine
    import numpy as np

    if pack_id == "supertonic":
        voice = engine.get_voice_style(style)
        wav, _duration = engine.synthesize(text, voice_style=voice, speed=float(speed), lang="en")
        samples = np.asarray(wav, dtype="float32").reshape(-1)
        return samples, int(engine.sample_rate)
    from piper import SynthesisConfig

    # Piper's length_scale is the inverse of speed: 0.9 is a little faster.
    config = SynthesisConfig(length_scale=1.0 / max(0.5, float(speed)))
    chunks = list(engine.synthesize(text, syn_config=config))
    if not chunks:
        return np.zeros(0, dtype="float32"), 22050
    samples = np.concatenate([chunk.audio_float_array for chunk in chunks]).astype("float32")
    return samples, int(chunks[0].sample_rate)
