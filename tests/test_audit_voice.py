"""Audit 1 (voice), 0.28.1: echo reference freshness, the keyword listener's
restart, faster loudness math, clipped recordings, and the Windows voice
that stays open between sentences."""

from __future__ import annotations

import io
import queue
import threading
import time
import types
import wave

import numpy as np
import pytest

from babysitter.plugins.voice import keyword, playback, turntaking, windows_voice


# ---- Echo reference ------------------------------------------------------

def test_the_echo_reference_goes_stale(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(playback.time, "monotonic", lambda: now[0])
    playback.publish_playback(b"\x10\x00" * 8)
    assert playback.latest_playback()
    now[0] += 0.5  # the reply ended half a second ago
    assert playback.latest_playback() == b""
    _chunk, echoed = turntaking.prepare_chunk(b"\x00\x01" * 800, True, playback.latest_playback())
    assert echoed is False  # so talk-over cannot fire in silence


def test_numpy_loudness_matches_the_plain_version():
    rng = np.random.default_rng(3)
    pcm = rng.integers(-20000, 20000, 800, dtype=np.int16).tobytes()
    other = rng.integers(-20000, 20000, 240, dtype=np.int16).tobytes()
    assert turntaking.rms(pcm) == pytest.approx(turntaking._rms_plain(pcm))
    assert turntaking.residual_pcm(pcm, other) == turntaking._residual_plain(pcm, other)
    assert turntaking.rms(b"") == 0.0 and turntaking.rms(b"\x01") == 0.0


def test_a_recording_past_full_scale_is_clipped_not_wrapped():
    from babysitter.plugins.voice.hearing import float_to_wav

    data = float_to_wav(np.array([1.5, -1.5, 0.5], dtype=np.float32))
    with wave.open(io.BytesIO(data)) as clip:
        samples = np.frombuffer(clip.readframes(3), dtype="<i2")
    assert list(samples) == [32767, -32767, 16383]


# ---- Keyword listener restart -------------------------------------------

def test_off_then_on_quickly_starts_a_fresh_listener(monkeypatch):
    monkeypatch.setattr(keyword, "packages_installed", lambda: True)
    monkeypatch.setattr(keyword, "model_ready", lambda: True)
    seen: list[threading.Event] = []
    release = threading.Event()

    def fake_run(self, word, on_phrase, on_status, on_error, stop=None):
        seen.append(stop)
        while not stop.is_set():
            time.sleep(0.01)
        release.wait(2)  # still closing (a model load, a capture) after Off

    monkeypatch.setattr(keyword.KeywordListener, "_run", fake_run)
    listener = keyword.KeywordListener()
    nothing = lambda *a: None  # noqa: E731
    listener.start("kari", nothing, nothing, nothing)
    time.sleep(0.05)
    listener.stop()
    assert not listener.running
    listener.start("kari", nothing, nothing, nothing)
    time.sleep(0.05)
    assert len(seen) == 2, "the second start must not be skipped while the first is closing"
    assert seen[0].is_set() and not seen[1].is_set()
    assert listener.running
    listener.stop()
    release.set()


# ---- Windows voice -------------------------------------------------------

class _FakePowerShell:
    """Answers 'ready', then 'done' for every line, unless told to hang."""

    def __init__(self, hang=False):
        self.lines: queue.Queue = queue.Queue()
        self.written: list[str] = []
        self.killed = False
        self.hang = hang
        self.lines.put(b"ready\n")
        outer = self

        class _In:
            def write(self, data):
                outer.written.append(data.decode())
                if not outer.hang:
                    outer.lines.put(b"done\n")

            def flush(self):
                pass

        class _Out:
            def __iter__(self):
                while True:
                    item = outer.lines.get()
                    if item is None:
                        return
                    yield item

        self.stdin, self.stdout = _In(), _Out()

    def poll(self):
        return 1 if self.killed else None

    def kill(self):
        self.killed = True
        self.lines.put(None)

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def fake_shell(monkeypatch):
    started: list[_FakePowerShell] = []

    def popen(args, **kwargs):
        proc = _FakePowerShell(hang=getattr(popen, "hang", False))
        started.append(proc)
        return proc

    monkeypatch.setattr(windows_voice, "popen_hidden", popen)
    monkeypatch.setattr(windows_voice, "available", lambda: True)
    monkeypatch.setattr("babysitter.platform.end_with_this_app", lambda proc: True)
    popen.started = started
    return popen


def test_one_program_says_every_sentence(fake_shell):
    speaker = windows_voice.WindowsSpeaker()
    speaker.speak("One.", "Microsoft Zira Desktop", 2)
    speaker.speak("Two\tthree\nfour.")
    assert len(fake_shell.started) == 1
    assert fake_shell.started[0].written == ["Microsoft Zira Desktop\t2\tOne.\n", "\t0\tTwo three four.\n"]
    speaker.close()


def test_stop_mid_sentence_ends_it_and_the_next_one_starts_fresh(fake_shell):
    fake_shell.hang = True
    speaker = windows_voice.WindowsSpeaker()
    worker = threading.Thread(target=speaker.speak, args=("A long sentence.",))
    worker.start()
    time.sleep(0.1)
    speaker.stop()
    worker.join(2)
    assert not worker.is_alive() and fake_shell.started[0].killed
    fake_shell.hang = False
    speaker.speak("Next.")
    assert len(fake_shell.started) == 2
    speaker.close()


def test_a_hung_voice_is_ended_after_the_time_limit(fake_shell, monkeypatch):
    fake_shell.hang = True
    monkeypatch.setattr(windows_voice, "SENTENCE_SECONDS", 0.2)
    speaker = windows_voice.WindowsSpeaker()
    with pytest.raises(windows_voice.WindowsVoiceError, match="too long"):
        speaker.speak("Hello.")
    assert fake_shell.started[0].killed


def test_an_idle_voice_closes_itself(fake_shell, monkeypatch):
    monkeypatch.setattr(windows_voice, "IDLE_SECONDS", 0.1)
    speaker = windows_voice.WindowsSpeaker()
    speaker.speak("Hello.")
    time.sleep(0.4)
    assert fake_shell.started[0].killed and speaker._proc is None


def test_the_words_never_reach_the_command_line():
    line = " ".join(windows_voice.speak_command())
    assert "Hello there" not in line and "$synth.Speak($parts[2])" in line
