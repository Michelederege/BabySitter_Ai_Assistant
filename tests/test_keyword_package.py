"""The packaged exe must not close when Vosk's folder is missing."""

import sys
from pathlib import Path

from babysitter.plugins.voice.keyword import packages_installed, vosk_dll_directory

ROOT = Path(__file__).resolve().parents[1]
_original_import = __import__


def test_a_real_vosk_folder_is_the_one_windows_searches(tmp_path):
    folder = tmp_path / "vosk"
    folder.mkdir()
    assert vosk_dll_directory(str(folder)) == str(folder)


def test_a_missing_temp_folder_uses_the_unpacked_vosk_libraries(tmp_path, monkeypatch):
    bundled = tmp_path / "vosk"
    bundled.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    missing = tmp_path / "Temp" / "_MEI" / "vosk"
    assert vosk_dll_directory(str(missing)) == str(bundled)


def test_no_vosk_folder_is_a_clear_miss(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    try:
        vosk_dll_directory(str(tmp_path / "missing"))
    except FileNotFoundError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("A missing folder should not look installed.")


def _import_allowing_sounddevice(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "sounddevice":
        return object()
    return _original_import(name, globals, locals, fromlist, level)


def test_a_broken_vosk_import_leaves_keyword_listening_off(monkeypatch):
    def broken():
        raise FileNotFoundError(r"C:\Users\you\AppData\Local\Temp\_MEI\vosk")

    monkeypatch.setattr("babysitter.plugins.voice.keyword._import_vosk", broken)
    monkeypatch.setattr("builtins.__import__", _import_allowing_sounddevice)
    assert packages_installed() is False


def test_the_exe_build_packs_the_vosk_libraries():
    text = (ROOT / "packaging" / "babysitter.spec").read_text(encoding="utf-8")
    assert "collect_dynamic_libs" in text
    assert '"vosk"' in text
    assert '"sounddevice"' in text
