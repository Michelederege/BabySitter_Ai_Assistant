"""Natural voices: real narrators through the Chatterbox helper. No model runs here."""

import hashlib
import sys

import numpy as np
import pytest

from babysitter import narrators
from babysitter.plugins.voice import clone_voice, engines


def test_eight_narrators_are_pinned_and_credited():
    assert len(narrators.NARRATORS) == 8
    for narrator in narrators.NARRATORS:
        assert len(narrator.sha256) == 64 and narrator.licence
    lj = narrators.BY_ID["lj"]
    assert "Public domain" in lj.licence and lj.member.endswith(".wav")
    assert all("CC BY 4.0" in n.licence for n in narrators.NARRATORS if n.source == "hifi")
    names = [name for name in engines.EXTRA_VOICES if engines.is_natural(name)]
    # The eight narrators, plus your own recorded voice (0.28.0).
    assert "Narrator: Linda Johnson (LJ Speech)" in names and len(names) == 9
    assert sum(name.startswith("Narrator: ") for name in names) == 8


def test_a_changed_clip_is_never_used(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    narrator = narrators.Narrator("t", "Test reader", "American", "CC0", hashlib.sha256(b"clip").hexdigest(), "hifi")
    path = narrators.clip_path(narrator)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"clip")
    assert narrators.verified_clip(narrator) == path
    path.write_bytes(b"swapped")
    with pytest.raises(narrators.NarratorError, match="changed"):
        narrators.verified_clip(narrator)


def test_the_helper_runs_isolated_in_its_own_python():
    assert clone_voice.env_python().parent.parent.name == "venv"
    steps = clone_voice.install_steps()
    assert steps[0][:3] == ["py", "-3.12", "-m"]
    assert any("torch==2.6.0" in step for step in steps[1]) and clone_voice.TORCH_INDEX in steps[1]
    assert "chatterbox-tts==0.1.7" in steps[2]


def test_no_room_on_the_card_means_kokoro_speaks_instead(monkeypatch):
    from babysitter.plugins.voice import kokoro_voice

    monkeypatch.setattr(clone_voice, "ready", lambda narrator_id: True)
    monkeypatch.setattr(clone_voice._worker, "running", lambda: False)
    monkeypatch.setattr(engines, "free_mib_hint", lambda: 1200)
    monkeypatch.setattr(kokoro_voice, "ready", lambda: True)
    monkeypatch.setattr(kokoro_voice, "_loaded_engine", lambda: object())
    monkeypatch.setattr(kokoro_voice, "_style", lambda name: "style")
    monkeypatch.setattr(kokoro_voice, "_render", lambda engine, text, style, speed, pitch, lang="en-us": (np.zeros(10, dtype="float32"), 24000))
    samples, rate = engines.render("Narrator: Linda Johnson (LJ Speech)", "Hello.")
    assert rate == 24000 and len(samples) == 10
    assert "only 1,200 MB is free" in engines.fallback_note()


def test_a_natural_voice_keeps_the_ai_on_low(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.controller import Controller

    controller = Controller()
    jobs: list = []
    monkeypatch.setattr(controller.worker, "submit", jobs.append)
    monkeypatch.setattr(controller.ollama, "port_open", lambda timeout=0.4: False)
    controller.settings.intelligence = "medium"
    controller.voice_wants_card = lambda: True
    controller.turn_on()
    from babysitter.intelligence import MODES

    assert jobs[-1][1] == MODES["low"].model
    assert controller.settings.intelligence == "medium"  # the saved choice is not changed


def test_the_exe_finds_its_packed_helper(tmp_path, monkeypatch):
    packed = tmp_path / "babysitter"
    packed.mkdir()
    (packed / "voiceclone_worker.py").write_text("# helper", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert clone_voice.worker_script() == packed / "voiceclone_worker.py"
    monkeypatch.delattr(sys, "_MEIPASS")
    assert clone_voice.worker_script().name == "voiceclone_worker.py" and clone_voice.worker_script().is_file()


def test_the_build_ships_the_helper_as_a_file():
    from pathlib import Path

    spec = (Path(__file__).resolve().parents[1] / "packaging" / "babysitter.spec").read_text(encoding="utf-8")
    assert '"voiceclone_worker.py"), "babysitter")' in spec
