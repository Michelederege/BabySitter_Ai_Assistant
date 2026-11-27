"""Heart and Sarah, the Kokoro voice picked in the Voice tab.

The voice files stay on this PC. Speech is generated on the processor,
not the graphics card. Voice cloning is not supported.
"""

from __future__ import annotations

import queue
import sys
import threading

from babysitter.paths import data_dir
from babysitter.platform import libraries_import, missing_from_exe, run_hidden, running_inside_exe
from babysitter.security import require_kokoro_model_url


MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin"
PACKAGES = ("kokoro-onnx==0.6.1", "sounddevice==0.5.6")

# Blends of Kokoro's own stock voices, as (voice, share) pairs that add to 1.
# Heart & Sarah is the starting preset. The EDITH-style blend is calm and
# crisp: Nova's clear diction and Kore's lower, steadier tone, with Heart,
# Kokoro's most natural voice, so it sounds like a person and not a machine.
# It is a mix of stock voices, not a copy of anyone's voice.
DEFAULT_VOICE = "Heart & Sarah blend"
BLENDS = {
    DEFAULT_VOICE: (("af_heart", 0.6), ("af_sarah", 0.4)),
    "EDITH-style blend": (("af_nova", 0.45), ("af_heart", 0.30), ("af_kore", 0.25)),
}
BLEND = BLENDS[DEFAULT_VOICE]

# How a voice is paced, on top of the speed slider: (speed factor, pause factor).
# The EDITH-style cadence is measured and unhurried, with a clear beat at
# each full stop. A voice not listed keeps the slider's speed and the
# usual pauses.
CADENCE = {
    "EDITH-style blend": (0.94, 1.3),
}


def cadence(voice_name: str) -> tuple[float, float]:
    return CADENCE.get(voice_name or DEFAULT_VOICE, (1.0, 1.0))
NAMED = {
    "af_heart": "af_heart",
    "af_nova": "af_nova",
    "af_kore": "af_kore",
    "am_michael": "am_michael",
    "bf_emma": "bf_emma",
    "bm_george": "bm_george",
}
# All 28 English Kokoro voices, by the name on the Voice tab ("Kokoro: Bella").
for _voice_id, _label in __import__("babysitter.voice_catalog", fromlist=["KOKORO_ENGLISH"]).KOKORO_ENGLISH:
    NAMED[f"Kokoro: {_label}"] = _voice_id


def kokoro_lang(voice_name: str) -> str:
    """British Kokoro voices (bf_, bm_) read with British pronunciation."""
    voice_id = NAMED.get(voice_name or "", "")
    return "en-gb" if voice_id.startswith(("bf_", "bm_")) else "en-us"


class KokoroError(Exception):
    """Heart and Sarah could not speak."""


def voice_dir():
    path = data_dir() / "models" / "kokoro"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_ready() -> bool:
    folder = voice_dir()
    return (folder / "kokoro-v1.0.onnx").is_file() and (folder / "voices-v1.0.bin").is_file()


def packages_installed() -> bool:
    # kokoro_onnx opens config.json while it imports. The packaged exe can
    # contain the Python and not that file. FileNotFoundError is not an
    # ImportError, and it used to close the window from the Voice page.
    return libraries_import("kokoro_onnx", "sounddevice")


def ready() -> bool:
    return packages_installed() and model_ready()


def install_command() -> list[str]:
    return [sys.executable, "-m", "pip", "install", *PACKAGES]


def download() -> str:
    """Download Heart and Sarah. The user must confirm before this runs."""
    for url in (MODEL_URL, VOICES_URL):
        require_kokoro_model_url(url)
    if not packages_installed():
        if running_inside_exe():
            raise KokoroError(missing_from_exe("Heart and Sarah"))
        completed = run_hidden(install_command(), timeout=900)
        output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        if completed.returncode not in (0, None):
            raise KokoroError(output[-1500:] or "The Kokoro voice programs did not install.")
    if not packages_installed():
        raise KokoroError(
            "Heart and Sarah's programs installed. Close BabySitter, open it again, "
            "and ask it something so the voice files can download."
        )
    folder = voice_dir()
    _fetch(MODEL_URL, folder / "kokoro-v1.0.onnx")
    _fetch(VOICES_URL, folder / "voices-v1.0.bin")
    if not model_ready():
        raise KokoroError("The voice files downloaded, but they were not usable.")
    return "Heart and Sarah is ready."


def _fetch(url: str, dest) -> None:
    from babysitter.security import keep_if_matching, require_matching_file

    require_kokoro_model_url(url)
    if keep_if_matching(url, dest):
        return
    from urllib import request as urlrequest


    temporary = dest.with_suffix(dest.suffix + ".part")
    with urlrequest.urlopen(url, timeout=180) as response, temporary.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
    try:
        require_matching_file(url, temporary)
    except ValueError as exc:
        temporary.unlink(missing_ok=True)
        raise KokoroError(str(exc)) from None
    temporary.replace(dest)


_engine = None
_styles: dict = {}
_lock = threading.Lock()
_playback_stop = threading.Event()


def warm() -> None:
    """Load Heart and Sarah before the first question, so that reply is not waiting on it."""
    if not ready():
        return
    _style(DEFAULT_VOICE)


def release() -> None:
    """Drop the voice from memory. The files stay on disk."""
    global _engine
    stop()
    with _lock:
        _engine = None
        _styles.clear()


def stop() -> None:
    """Stop Heart and Sarah. The microphone stream is left open.

    sounddevice.stop() closes every stream in the process, including the
    keyword listener. The playback loop watches _playback_stop and closes
    its own output stream.
    """
    _playback_stop.set()


def _float_to_pcm16(samples) -> bytes:
    """Convert float [-1.0, 1.0] samples to signed 16-bit little-endian PCM."""
    try:
        import numpy as np

        arr = np.asarray(samples, dtype=np.float32)
        return np.clip(arr * 32767.0, -32767.0, 32767.0).astype("<i2").tobytes()
    except ImportError:
        pcm = bytearray()
        for value in samples:
            clamped = max(-1.0, min(1.0, float(value)))
            pcm += int(clamped * 32767).to_bytes(2, "little", signed=True)
        return bytes(pcm)


def render_clip(text: str, voice_name: str = DEFAULT_VOICE) -> tuple[bytes, int]:
    """One int16 clip in the chosen voice. Used to pre-render filler lines."""
    if not ready():
        raise KokoroError("Heart and Sarah is not downloaded yet.")
    engine = _loaded_engine()
    samples, rate = _render(engine, text, _style(voice_name or DEFAULT_VOICE), 1.05, -1)
    return _float_to_pcm16(samples), int(rate)


def speak_sequence(
    pieces,
    voice_name: str,
    speed_percent: int,
    pitch: int,
    on_start=None,
    on_piece=None,
    incoming: queue.Queue | None = None,
    render=None,
) -> None:
    """Say each piece in order. Later pieces can arrive while the first is still playing.

    One playback stream stays open for the whole reply. Opening a new stream
    for every sentence was the pause after the first line. The next piece is
    built while the current one plays.
    """
    waiting = [piece.strip() for piece in pieces if piece and piece.strip()]
    if render is not None:
        # Another engine (Piper, Supertonic) makes the audio. The same player
        # and stream say it, so echo cancellation and talk-over still apply.
        return _play_sequence(waiting, incoming, render, 1.0, on_start, on_piece)
    if waiting and cadence(voice_name)[1] > 1.0:
        # A measured voice gives "Understood." its own beat before the answer.
        from babysitter.plugins.voice.speech import beat_after_opener

        waiting = beat_after_opener(waiting[0]) + waiting[1:]
    if not waiting and incoming is None:
        return
    if not ready():
        raise KokoroError("Heart and Sarah is not downloaded yet.")
    _playback_stop.clear()
    style = _style(voice_name)
    speed_factor, pause_factor = cadence(voice_name)
    speed = max(0.5, min(2.0, int(speed_percent) / 100 * speed_factor))
    engine = _loaded_engine()
    audio: queue.Queue = queue.Queue(maxsize=2)

    def produce() -> None:
        try:
            index = 0
            while not _playback_stop.is_set():
                if index < len(waiting):
                    piece = waiting[index]
                    index += 1
                elif incoming is None:
                    break
                else:
                    piece = incoming.get()
                    if piece is None or _playback_stop.is_set():
                        break
                try:
                    from babysitter.plugins.voice.speech import pause_ms

                    samples, rate = _render(engine, piece, style, speed, pitch, kokoro_lang(voice_name))
                    samples = trim_edges(samples, rate, tail_ms=int(pause_ms(piece) * pause_factor))
                except Exception:
                    break
                audio.put((piece, samples, rate))
        finally:
            audio.put(None)

    threading.Thread(target=produce, name="babysitter-voice", daemon=True).start()
    started = False
    stream = None
    stream_rate = None
    try:
        while not _playback_stop.is_set():
            item = audio.get()
            if item is None or _playback_stop.is_set():
                break
            piece, samples, rate = item
            if stream is None or stream_rate != rate:
                if stream is not None:
                    stream.stop()
                    stream.close()
                import sounddevice as sd

                stream = sd.OutputStream(samplerate=rate, channels=1, dtype="float32")
                stream.start()
                stream_rate = rate
            if not started:
                started = True
                if on_start is not None:
                    on_start()
            finished = _play_into(samples, rate, stream.write)
            if finished and on_piece is not None:
                on_piece(piece)
            if not finished:
                break
    finally:
        if stream is not None:
            stream.stop()
            stream.close()


def _play_sequence(waiting, incoming, render, pause_factor, on_start, on_piece) -> None:
    from babysitter.plugins.voice.speech import pause_ms

    _playback_stop.clear()
    audio: queue.Queue = queue.Queue(maxsize=2)

    def produce() -> None:
        try:
            index = 0
            while not _playback_stop.is_set():
                if index < len(waiting):
                    piece = waiting[index]
                    index += 1
                elif incoming is None:
                    break
                else:
                    piece = incoming.get()
                    if piece is None or _playback_stop.is_set():
                        break
                try:
                    samples, rate = render(piece)
                    samples = trim_edges(samples, rate, tail_ms=int(pause_ms(piece) * pause_factor))
                except Exception:
                    break
                audio.put((piece, samples, rate))
        finally:
            audio.put(None)

    threading.Thread(target=produce, name="babysitter-voice", daemon=True).start()
    started = False
    stream = None
    stream_rate = None
    try:
        while not _playback_stop.is_set():
            item = audio.get()
            if item is None or _playback_stop.is_set():
                break
            piece, samples, rate = item
            if stream is None or stream_rate != rate:
                if stream is not None:
                    stream.stop()
                    stream.close()
                import sounddevice as sd

                stream = sd.OutputStream(samplerate=rate, channels=1, dtype="float32")
                stream.start()
                stream_rate = rate
            if not started:
                started = True
                if on_start is not None:
                    on_start()
            finished = _play_into(samples, rate, stream.write)
            if finished and on_piece is not None:
                on_piece(piece)
            if not finished:
                break
    finally:
        if stream is not None:
            stream.stop()
            stream.close()


def trim_edges(samples, sample_rate: int, lead_ms: int = 40, tail_ms: int = 180, threshold: float = 0.02):
    """Drop the long silence Kokoro puts on each piece, and keep a short breath.

    A whole reply can keep its own pauses. The padding on every piece is what
    stacks into a stall when the next sentence starts.
    """
    try:
        count = len(samples)
    except TypeError:
        return samples
    if count == 0 or int(sample_rate) <= 0:
        return samples
    rate = int(sample_rate)
    window = min(count, int(rate * 0.9))
    start = 0
    found = False
    end = count
    if hasattr(samples, "dtype"):
        try:
            import numpy as np

            head = np.flatnonzero(np.abs(samples[:window]) > threshold)
            if head.size == 0:
                return samples
            start = int(head[0])
            found = True
            tail_from = max(count - window, start)
            tail = np.flatnonzero(np.abs(samples[tail_from:]) > threshold)
            if tail.size > 0:
                end = tail_from + int(tail[-1]) + 1
        except Exception:
            found = False
    if not found:
        for index in range(window):
            if abs(float(samples[index])) > threshold:
                start = index
                found = True
                break
        if not found:
            return samples
        for index in range(count - 1, max(count - window, start) - 1, -1):
            if abs(float(samples[index])) > threshold:
                end = index + 1
                break
    start = max(0, start - int(rate * lead_ms / 1000))
    end = min(count, end + int(rate * tail_ms / 1000))
    if end - start < max(1, rate // 20):
        return samples
    return samples[start:end]


def _render(engine, text: str, style, speed: float, pitch: int, lang: str = "en-us"):
    with _lock:
        samples, sample_rate = engine.create(text, voice=style, speed=speed, lang=lang)
    # A one-step pitch change also slows the words down, which is what made the
    # default voice sound dragged. Larger steps on the slider still shift pitch.
    if abs(int(pitch)) < 2:
        return samples, sample_rate
    shifted = int(sample_rate * (2 ** (int(pitch) / 12)))
    shifted = max(8000, min(48000, shifted))
    return samples, shifted


def _play_into(samples, sample_rate: int, write, block_ms: int = 10) -> bool:
    """Play raw audio in 10 ms blocks on a stream that stays open."""
    from babysitter.plugins.voice.playback import play_pcm_blocks, publish_playback

    try:
        return play_pcm_blocks(
            samples,
            sample_rate,
            _playback_stop,
            write,
            block_ms=block_ms,
            publish=publish_playback,
        )
    except Exception:
        return False


def _voice_threads() -> int:
    import os

    return 8 if (os.cpu_count() or 4) >= 16 else 4


def _limit_onnx_threads() -> None:
    """Cap Kokoro's threads and stop it spinning while it waits.

    Eight threads on a processor with 16 or more (about 25% faster per
    sentence on his 24-thread PC: 0.56 s instead of 0.75 s), four otherwise,
    so a game still has most of the cores.
    """
    try:
        import onnxruntime as ort
    except ImportError:
        return
    if getattr(ort.InferenceSession, "_babysitter_capped", False):
        return
    original = ort.InferenceSession

    def limited(*args, **kwargs):
        if "sess_options" not in kwargs and len(args) < 2:
            options = ort.SessionOptions()
            options.intra_op_num_threads = _voice_threads()
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            try:
                options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            except Exception:
                pass
            kwargs["sess_options"] = options
        return original(*args, **kwargs)

    limited._babysitter_capped = True  # type: ignore[attr-defined]
    ort.InferenceSession = limited


def _loaded_engine():
    global _engine
    with _lock:
        if _engine is None:
            if not ready():
                raise KokoroError("Heart and Sarah is not downloaded yet.")
            from kokoro_onnx import Kokoro

            from babysitter.security import require_loaded_file

            _limit_onnx_threads()
            folder = voice_dir()
            model, voices = folder / "kokoro-v1.0.onnx", folder / "voices-v1.0.bin"
            try:
                require_loaded_file(MODEL_URL, model)
                require_loaded_file(VOICES_URL, voices)
            except ValueError as exc:
                raise KokoroError(str(exc)) from None
            _engine = Kokoro(str(model), str(voices))
        return _engine


def _style(voice_name: str):
    name = voice_name or DEFAULT_VOICE
    cached = _styles.get(name)
    if cached is not None:
        return cached
    single = NAMED.get(name)
    if single:
        _styles[name] = single
        return single
    engine = _loaded_engine()
    parts = BLENDS.get(name, BLENDS[DEFAULT_VOICE])
    blended = sum(engine.get_voice_style(voice) * share for voice, share in parts)
    _styles[name] = blended
    return blended
