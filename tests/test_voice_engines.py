"""The extra hearing engines and voices. No real model is loaded here."""

import io
import tarfile

import pytest

from babysitter import modelpacks


def test_every_pack_is_pinned_and_from_an_allowed_place():
    for pack in modelpacks.PACKS.values():
        sources = [pack.archive] if pack.archive else [(modelpacks.SUPERTONIC + rel, sha) for rel, sha in pack.files]
        assert sources, pack.id
        for url, sha in sources:
            assert url.startswith(("https://github.com/k2-fsa/sherpa-onnx/releases/download/", modelpacks.SUPERTONIC))
            assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha), url


def _archive(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _with_pack(monkeypatch, payload: bytes):
    import hashlib

    pack = modelpacks.Pack("t", "Test pack", "voice", 1, archive=(modelpacks.SHERPA_TTS + "t.tar.bz2", hashlib.sha256(payload).hexdigest()))
    monkeypatch.setitem(modelpacks.PACKS, "t", pack)
    return lambda url, timeout=0: _Response(payload)


def test_a_pack_downloads_checks_unpacks_and_is_checked_before_load(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    opener = _with_pack(monkeypatch, _archive({"voice/model.onnx": b"weights", "voice/tokens.txt": b"a b"}))
    assert modelpacks.download("t", opener) == "Test pack is on this PC."
    folder = modelpacks.verify("t")
    assert modelpacks.find(folder, "*.onnx").read_bytes() == b"weights"
    (folder / "voice" / "model.onnx").write_bytes(b"swapped!")
    with pytest.raises(modelpacks.PackError, match="changed"):
        modelpacks.verify("t")


def test_a_tampered_or_unsafe_pack_is_not_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    opener = _with_pack(monkeypatch, _archive({"../escape.txt": b"x"}))
    with pytest.raises(modelpacks.PackError, match="unsafe"):
        modelpacks.download("t", opener)
    assert not modelpacks.ready("t") and not (tmp_path / "escape.txt").exists()
    _with_pack(monkeypatch, b"the pinned bytes")
    with pytest.raises(modelpacks.PackError, match="did not match"):
        modelpacks.download("t", lambda url, timeout=0: _Response(b"something else"))
    assert not modelpacks.ready("t")


def test_a_clock_time_written_with_a_dot_is_read_as_a_time(monkeypatch):
    import re

    from babysitter.plugins.voice import engines

    class Stream:
        result = type("R", (), {"text": "remind me at 6.30 that pi is 3.14"})()

        def accept_waveform(self, *_):
            pass

    class Recognizer:
        def create_stream(self):
            return Stream()

        def decode_stream(self, _stream):
            pass

    monkeypatch.setattr(engines, "ready", lambda _engine: True)
    monkeypatch.setitem(engines._loaded, "moonshine", Recognizer())
    monkeypatch.setattr(engines, "_samples", lambda wav: ([0.0], 16000))
    assert engines.hear("moonshine", b"wav") == "remind me at 6:30 that pi is 3.14"
    engines.release()


def test_a_voice_whose_files_are_missing_falls_back_to_the_windows_voice(tmp_path, monkeypatch):
    import json

    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    try:
        (tmp_path / "data" / "voice.json").write_text(json.dumps({"voice": "Piper: HFC female", "speed": 100}), encoding="utf-8")
        prefs = shell._voice_prefs()
        assert prefs["engine"] == "windows" and "until Piper: HFC female is downloaded" in prefs["label"]
        # A hearing engine not downloaded yet leaves Whisper hearing the question.
        controller.settings.hearing_engine = "parakeet"
        assert shell._hearing_engine() == "whisper"
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()
