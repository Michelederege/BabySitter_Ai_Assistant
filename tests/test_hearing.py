"""Hearing chooses a line, and a bad list file is kept."""

import json

from babysitter.deskstore import add_item, load_list
from babysitter.plugins.voice.hearing import pcm16_to_wav
from babysitter.responsiveness import ResponsivenessLog


def test_a_bad_list_is_moved_aside_before_a_new_item_is_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    target = tmp_path / "schedule.json"
    target.write_text("{not a list", encoding="utf-8")
    assert load_list("schedule.json") == []
    saved = (tmp_path / "schedule.json.bak").read_text(encoding="utf-8")
    assert saved == "{not a list"
    assert not target.exists()
    add_item("schedule.json", text="stretch")
    fresh = json.loads(target.read_text(encoding="utf-8"))
    assert fresh[0]["text"] == "stretch"
    assert (tmp_path / "schedule.json.bak").read_text(encoding="utf-8") == "{not a list"


def test_a_full_microphone_queue_keeps_the_newest_sound():
    import queue

    from babysitter.plugins.voice.keyword import offer_audio

    audio = queue.Queue(maxsize=2)
    offer_audio(audio, b"one")
    offer_audio(audio, b"two")
    offer_audio(audio, b"three")
    assert audio.get_nowait() == b"two"
    assert audio.get_nowait() == b"three"


def test_silence_and_a_short_hint_do_not_replace_the_real_command():
    from babysitter.plugins.voice.hearing import Transcript, hallucinated, merge_lines

    assert hallucinated("Thanks for watching!")
    assert hallucinated("you")
    assert not hallucinated("thank you")
    vague = Transcript("what time is it", True)
    chosen = merge_lines("remind me to stretch", vague)
    assert chosen.text == "remind me to stretch"
    longer = Transcript("remind me to stretch at noon", True)
    assert merge_lines("what time is it", longer).text.startswith("remind me to stretch")


def test_pcm_becomes_a_wav_and_the_text_time_is_reported():
    wav = pcm16_to_wav((b"\x00\x00") * 160)
    assert wav[:4] == b"RIFF"
    log = ResponsivenessLog()
    log.add({"first_sound": 900, "transcript": 400})
    assert "became text after 400 ms" in log.summary()
