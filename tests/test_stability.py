"""Stability: the voice player, the natural-voice helper, and the error hooks.

Five simulations each, like the rest of the repo: normal use, stop
mid-reply, a voice that fails at once, a voice that fails later, and a
helper that hangs or talks nonsense.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
import types

import numpy as np
import pytest

from babysitter.plugins.voice import clone_voice, kokoro_voice


class _FakeStream:
    def __init__(self, samplerate, channels, dtype):
        self.rate = samplerate
        self.written = 0

    def start(self):
        pass

    def write(self, block):
        self.written += len(block)

    def stop(self):
        pass

    def close(self):
        pass


@pytest.fixture
def fake_audio(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(OutputStream=_FakeStream))
    kokoro_voice._playback_stop.clear()
    yield
    kokoro_voice._playback_stop.clear()


def _voice_threads() -> int:
    return sum(1 for thread in threading.enumerate() if thread.name == "babysitter-voice")


def _wait_until(test, seconds=3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if test():
            return True
        time.sleep(0.02)
    return test()


def _tone(_piece):
    return np.zeros(240, dtype=np.float32), 24000


def test_every_piece_is_said_in_order(fake_audio):
    said = []
    kokoro_voice._play_sequence(["One.", "Two.", "Three."], None, _tone, 1.0, None, said.append)
    assert said == ["One.", "Two.", "Three."]


def test_late_pieces_arrive_while_speaking(fake_audio):
    incoming: queue.Queue = queue.Queue()
    said = []

    def feed():
        time.sleep(0.05)
        incoming.put("Later.")
        incoming.put(None)

    threading.Thread(target=feed, daemon=True).start()
    kokoro_voice._play_sequence(["First."], incoming, _tone, 1.0, None, said.append)
    assert said == ["First.", "Later."]


def test_stop_leaves_no_stuck_helper_thread(fake_audio):
    """Stopped with more coming and nobody closing the input: the helper used to wait forever."""
    before = _voice_threads()
    incoming: queue.Queue = queue.Queue()  # never closed
    said = []

    def on_piece(piece):
        said.append(piece)
        kokoro_voice._playback_stop.set()

    kokoro_voice._play_sequence(["One.", "Two.", "Three.", "Four."], incoming, _tone, 1.0, None, on_piece)
    assert said == ["One."]
    assert _wait_until(lambda: _voice_threads() <= before)


def test_a_voice_that_fails_at_once_says_so(fake_audio):
    def broken(_piece):
        raise RuntimeError("no model")

    with pytest.raises(kokoro_voice.KokoroError):
        kokoro_voice._play_sequence(["Hello."], None, broken, 1.0, None, None)


def test_a_voice_that_fails_later_keeps_what_it_said(fake_audio):
    said = []

    def second_breaks(piece):
        if piece == "Two.":
            raise RuntimeError("out of memory")
        return _tone(piece)

    kokoro_voice._play_sequence(["One.", "Two.", "Three."], None, second_breaks, 1.0, None, said.append)
    assert said == ["One."]


# ---- The natural-voice helper -------------------------------------------

class _FakeProc:
    def __init__(self):
        self.stdin = types.SimpleNamespace(write=lambda text: None, flush=lambda: None, close=lambda: None)
        self.killed = False

    def poll(self):
        return 1 if self.killed else None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


def _worker_with(lines):
    worker = clone_voice._Worker()
    worker._proc = _FakeProc()
    worker._lines = queue.Queue()
    for line in lines:
        worker._lines.put(line)
    return worker


def test_a_hung_helper_is_closed_after_the_time_limit(monkeypatch):
    monkeypatch.setattr(clone_voice, "SENTENCE_SECONDS", 0.2)
    worker = _worker_with([])
    proc = worker._proc
    with pytest.raises(clone_voice.CloneError, match="stopped answering"):
        worker.speak("Hello.", "clip.wav")
    assert proc.killed and not worker.running()


def test_a_garbled_reply_closes_the_helper():
    worker = _worker_with(["this is not json\n"])
    with pytest.raises(clone_voice.CloneError, match="could not read"):
        worker.speak("Hello.", "clip.wav")
    assert not worker.running()


def test_a_helper_that_closed_its_input(monkeypatch):
    worker = _worker_with([])

    def broken(_text):
        raise BrokenPipeError

    worker._proc.stdin.write = broken
    with pytest.raises(clone_voice.CloneError, match="stopped"):
        worker.speak("Hello.", "clip.wav")


def test_a_good_reply_is_audio():
    import base64
    import json

    samples = np.arange(4, dtype=np.float32)
    reply = json.dumps({"id": 1, "rate": 24000, "samples": base64.b64encode(samples.tobytes()).decode()})
    worker = _worker_with([reply + "\n"])
    audio, rate = worker.speak("Hello.", "clip.wav")
    assert rate == 24000 and list(audio) == [0, 1, 2, 3]


def test_a_helper_error_is_a_sentence_and_keeps_it_running():
    worker = _worker_with(['{"id": 1, "error": "CUDA busy"}\n'])
    with pytest.raises(clone_voice.CloneError, match="CUDA busy"):
        worker.speak("Hello.", "clip.wav")
    assert worker.running()


# ---- Error hooks ----------------------------------------------------------

def test_the_same_error_shows_one_box(monkeypatch):
    from babysitter import app

    boxes = []
    monkeypatch.setattr(app, "panic", boxes.append)
    monkeypatch.setattr(app, "_shown", set())
    for _ in range(5):
        try:
            raise FileNotFoundError("vosk")
        except FileNotFoundError:
            app._hook(*sys.exc_info())
    try:
        raise ValueError("another")
    except ValueError:
        app._hook(*sys.exc_info())
    assert len(boxes) == 2


def test_a_thread_error_is_logged_not_lost(monkeypatch):
    from babysitter import app

    logged = []
    monkeypatch.setattr(app, "get_logger", lambda: types.SimpleNamespace(error=lambda *a: logged.append(a)))
    previous = threading.excepthook
    threading.excepthook = app._thread_hook
    try:
        thread = threading.Thread(target=lambda: 1 / 0, name="babysitter-test")
        thread.start()
        thread.join()
    finally:
        threading.excepthook = previous
    assert logged and "babysitter-test" in logged[0][1] and "ZeroDivisionError" in logged[0][2]


def test_ctrl_c_shows_no_box(monkeypatch):
    from babysitter import app

    boxes = []
    monkeypatch.setattr(app, "panic", boxes.append)
    app._hook(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert boxes == []
