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


def test_pcm_becomes_a_wav_and_the_text_time_is_reported():
    wav = pcm16_to_wav((b"\x00\x00") * 160)
    assert wav[:4] == b"RIFF"
    log = ResponsivenessLog()
    log.add({"first_sound": 900, "transcript": 400})
    assert "became text after 400 ms" in log.summary()
