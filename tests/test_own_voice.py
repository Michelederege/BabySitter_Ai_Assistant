"""Your own voice: five simulations (a good take, silence, too quiet, too
short, a swapped file), plus how it joins the voice list and the helper."""

from __future__ import annotations

import numpy as np
import pytest

from babysitter import ownvoice

RATE = 16000


def _speech(seconds: float, level: float = 0.2, gap: float = 1.0) -> np.ndarray:
    """A take: `gap` seconds of room noise, then a tone standing in for speech, then room noise."""
    rng = np.random.default_rng(1)
    quiet = rng.normal(0, 0.0005, int(gap * RATE)).astype(np.float32)
    t = np.arange(int(seconds * RATE)) / RATE
    voice = (level * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    return np.concatenate([quiet, voice, quiet])


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setattr(ownvoice, "data_dir", lambda: tmp_path)
    return tmp_path


def test_a_good_take_is_saved_trimmed_and_checked(data_home):
    message = ownvoice.save(_speech(10), RATE)
    assert "saved on this PC" in message and ownvoice.ready()
    kept = ownvoice.verified_clip()
    import wave

    with wave.open(str(kept)) as clip:
        seconds = clip.getnframes() / clip.getframerate()
    assert 10 <= seconds < 10.6  # the second of quiet each side is trimmed to 0.15 s


def test_silence_is_refused(data_home):
    with pytest.raises(ownvoice.OwnVoiceError, match="silence"):
        ownvoice.save(np.zeros(RATE * 15, dtype=np.float32), RATE)
    assert not ownvoice.ready()


def test_too_quiet_is_refused(data_home):
    with pytest.raises(ownvoice.OwnVoiceError, match="too quiet"):
        ownvoice.save(_speech(10, level=0.005), RATE)


def test_too_little_speech_is_refused(data_home):
    with pytest.raises(ownvoice.OwnVoiceError, match="need at least 6"):
        ownvoice.save(_speech(3, gap=6), RATE)


def test_clipped_take_is_refused(data_home):
    with pytest.raises(ownvoice.OwnVoiceError, match="too loud"):
        ownvoice.save(np.clip(_speech(10, level=3.0), -1, 1), RATE)


def test_a_swapped_file_is_not_used(data_home):
    ownvoice.save(_speech(10), RATE)
    ownvoice.clip_path().write_bytes(ownvoice.wav_bytes(_speech(9), RATE))
    with pytest.raises(ownvoice.OwnVoiceError, match="changed"):
        ownvoice.verified_clip()


def test_delete_removes_both_files(data_home):
    ownvoice.save(_speech(10), RATE)
    assert "deleted" in ownvoice.delete()
    assert not ownvoice.clip_path().exists() and not ownvoice.record_path().exists()
    assert "no voice recording" in ownvoice.delete()


def test_it_is_a_natural_voice_in_the_list():
    from babysitter.plugins.voice.engines import EXTRA_VOICES, is_natural

    assert is_natural(ownvoice.OWN_NAME)
    assert EXTRA_VOICES[ownvoice.OWN_NAME] == ("chatterbox", ownvoice.OWN_ID)
    assert not is_natural("Kokoro: Bella")


def test_the_helper_uses_the_checked_recording(data_home, monkeypatch):
    from babysitter.plugins.voice import clone_voice

    with pytest.raises(clone_voice.CloneError, match="not recorded"):
        clone_voice._checked_clip(ownvoice.OWN_ID)
    ownvoice.save(_speech(10), RATE)
    assert clone_voice._checked_clip(ownvoice.OWN_ID) == ownvoice.clip_path()
    monkeypatch.setattr(clone_voice, "environment_ready", lambda: True)
    monkeypatch.setattr("babysitter.modelpacks.ready", lambda pack: True)
    assert clone_voice.ready(ownvoice.OWN_ID)


def test_consent_text_names_who_may_be_recorded():
    assert "your own voice" in ownvoice.CONSENT
    assert "agrees" in ownvoice.CONSENT and "never sent" in ownvoice.CONSENT
