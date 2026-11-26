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

# The starting preset: af_heart 60% + af_sarah 40%.
BLEND = ("af_heart", "af_sarah", 0.6, 0.4)
NAMED = {
    "af_heart": "af_heart",
    "am_michael": "am_michael",
    "bf_emma": "bf_emma",
    "bm_george": "bm_george",
}


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
    require_kokoro_model_url(url)
    if dest.is_file() and dest.stat().st_size > 0:
        return
    from urllib import request as urlrequest

    from babysitter.security import require_matching_file

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
    _style("Heart & Sarah blend")


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


def render_clip(text: str) -> tuple[bytes, int]:
    """One int16 clip from Heart and Sarah. Used to pre-render filler lines."""
    if not ready():
        raise KokoroError("Heart and Sarah is not downloaded yet.")
    engine = _loaded_engine()
    samples, rate = _render(engine, text, _style("Heart & Sarah blend"), 1.05, -1)
    pcm = bytearray()
    for value in samples:
        clamped = max(-1.0, min(1.0, float(value)))
        pcm += int(clamped * 32767).to_bytes(2, "little", signed=True)
    return bytes(pcm), int(rate)


def speak_sequence(
    pieces,
    voice_name: str,
    speed_percent: int,
    pitch: int,
    on_start=None,
    on_piece=None,
    incoming: queue.Queue | None = None,
) -> None:
    """Say each piece in order. Later pieces can arrive while the first is still playing.

    One playback stream stays open for the whole reply. Opening a new stream
    for every sentence was the pause after the first line. The next piece is
    built while the current one plays.
    """
    waiting = [piece.strip() for piece in pieces if piece and piece.strip()]
    if not waiting and incoming is None:
        return
    if not ready():
        raise KokoroError("Heart and Sarah is not downloaded yet.")
    _playback_stop.clear()
    style = _style(voice_name)
    speed = max(0.5, min(2.0, int(speed_percent) / 100))
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
                    samples, rate = _render(engine, piece, style, speed, pitch)
                    samples = trim_edges(samples, rate)
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
    for index in range(window):
        if abs(float(samples[index])) > threshold:
            start = index
            found = True
            break
    if not found:
        return samples
    end = count
    for index in range(count - 1, max(count - window, start) - 1, -1):
        if abs(float(samples[index])) > threshold:
            end = index + 1
            break
    start = max(0, start - int(rate * lead_ms / 1000))
    end = min(count, end + int(rate * tail_ms / 1000))
    if end - start < max(1, rate // 20):
        return samples
    return samples[start:end]


def _render(engine, text: str, style, speed: float, pitch: int):
    with _lock:
        samples, sample_rate = engine.create(text, voice=style, speed=speed, lang="en-us")
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


def _limit_onnx_threads() -> None:
    """Cap Kokoro at four threads and stop it spinning while it waits."""
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
            options.intra_op_num_threads = 4
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

            _limit_onnx_threads()
            folder = voice_dir()
            _engine = Kokoro(str(folder / "kokoro-v1.0.onnx"), str(folder / "voices-v1.0.bin"))
        return _engine


def _style(voice_name: str):
    name = voice_name or "Heart & Sarah blend"
    cached = _styles.get(name)
    if cached is not None:
        return cached
    single = NAMED.get(name)
    if single:
        _styles[name] = single
        return single
    engine = _loaded_engine()
    heart, sarah, heart_share, sarah_share = BLEND
    blended = engine.get_voice_style(heart) * heart_share + engine.get_voice_style(sarah) * sarah_share
    _styles[name] = blended
    return blended
