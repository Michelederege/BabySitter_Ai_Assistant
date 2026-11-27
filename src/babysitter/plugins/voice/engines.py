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

def _extra_voices() -> dict[str, tuple[str, str]]:
    """Every Piper and Supertonic voice in the catalog: name -> (pack id, speaker or style)."""
    from babysitter.voice_catalog import catalog

    return {voice.name: (voice.pack, voice.speaker) for voice in catalog() if voice.engine in {"piper", "supertonic", "natural"}}


def is_natural(name: str) -> bool:
    """A voice the Chatterbox helper speaks: a narrator, or your own recording."""
    from babysitter.ownvoice import OWN_NAME

    return (name or "").startswith("Narrator: ") or name == OWN_NAME


# Shown on the Voice tab. The value is (pack id, speaker index or style).
EXTRA_VOICES = _extra_voices()

_lock = threading.Lock()
_loaded: dict[str, object] = {}


class EngineError(Exception):
    """An extra engine could not be used. The message says what to do."""


def release() -> None:
    """Drop every loaded engine, and close the natural-voice helper. The files stay on disk."""
    with _lock:
        _loaded.clear()
    try:
        from babysitter.plugins.voice.clone_voice import release as release_natural

        release_natural()
    except Exception:
        pass


def _threads() -> int:
    from babysitter.plugins.voice.kokoro_voice import _voice_threads

    return _voice_threads()


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
    if pack is not None and is_natural(name):
        from babysitter.plugins.voice.clone_voice import ready as natural_ready

        return natural_ready(pack[1])
    return pack is not None and ready(pack[0])


# The shell sets this to the free video memory it last read, so a natural
# voice is started only when the card has room for it.
free_mib_hint = lambda: None  # noqa: E731
_fallback_said = {"note": ""}


def fallback_note() -> str:
    """The sentence explaining the last time Kokoro stood in. Empty after it is read."""
    note, _fallback_said["note"] = _fallback_said["note"], ""
    return note


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
    if is_natural(name):
        from babysitter.plugins.voice import kokoro_voice
        from babysitter.plugins.voice.clone_voice import CloneError, render as natural_render

        try:
            return natural_render(style, text, free_mib_hint())
        except CloneError as exc:
            # Never silent: Kokoro says the sentence, and the reason is kept for the screen.
            _fallback_said["note"] = str(exc)
            if not kokoro_voice.ready():
                raise EngineError(str(exc)) from None
            engine = kokoro_voice._loaded_engine()
            return kokoro_voice._render(engine, text, kokoro_voice._style(kokoro_voice.DEFAULT_VOICE), float(speed), 0)
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
    # A pack with many speakers picks one by its number in the model.
    config = SynthesisConfig(
        length_scale=1.0 / max(0.5, float(speed)),
        speaker_id=int(style) if str(style).isdigit() else None,
    )
    chunks = list(engine.synthesize(text, syn_config=config))
    if not chunks:
        return np.zeros(0, dtype="float32"), 22050
    samples = np.concatenate([chunk.audio_float_array for chunk in chunks]).astype("float32")
    return samples, int(chunks[0].sample_rate)
