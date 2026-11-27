"""0.30.0: the best engine for each job, as measured on his PC."""

from __future__ import annotations

import pytest


def _shell(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    return Shell(Controller())


@pytest.mark.parametrize("chosen, downloaded, hears", [
    ("parakeet", {"parakeet", "moonshine"}, "parakeet"),
    ("parakeet", {"moonshine"}, "moonshine"),   # Parakeet not here yet: the next fast one
    ("parakeet", set(), "whisper"),
    ("moonshine", {"parakeet", "moonshine"}, "moonshine"),  # picked by hand: kept
    ("moonshine", {"parakeet"}, "parakeet"),
    ("whisper", {"parakeet", "moonshine"}, "whisper"),  # picked by hand: kept
])
def test_hearing_falls_back_to_the_next_best_engine(tmp_path, monkeypatch, chosen, downloaded, hears):
    shell = _shell(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr("babysitter.modelpacks.ready", lambda pack: pack in downloaded)
        shell.controller.settings.hearing_engine = chosen
        assert shell._hearing_engine() == hears
    finally:
        shell.window.close()


def test_kokoros_thread_cap_keeps_inference_session_a_class():
    """Supertonic checks isinstance(session, ort.InferenceSession). Kokoro's thread
    cap replaced that class with a function, so Supertonic failed to load."""
    ort = pytest.importorskip("onnxruntime")
    from babysitter.plugins.voice import kokoro_voice

    original = ort.InferenceSession
    try:
        kokoro_voice._limit_onnx_threads()
        capped = ort.InferenceSession
        assert isinstance(capped, type), "must stay a class"
        assert getattr(capped, "_babysitter_capped", False)
        kokoro_voice._limit_onnx_threads()
        assert ort.InferenceSession is capped, "capped once, not wrapped again"
    finally:
        ort.InferenceSession = original


def test_parakeet_is_the_default_and_moonshine_defaults_move_to_it():
    from babysitter.settings import Settings, migrate

    assert Settings().hearing_engine == "parakeet"
    assert migrate({"schema_version": 14, "hearing_engine": "moonshine"})["hearing_engine"] == "parakeet"
