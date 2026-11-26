"""A missing file inside the packaged exe must not close the window.

Kokoro opens config.json while it imports. Vosk asks Windows for a temp
folder that was never unpacked. Those are not ImportError, so the old
check let them reach the error box. The same hole is open for the
microphone DLL, the hearing programs, and the sharper memory.
"""

import sys
from pathlib import Path

from babysitter.platform import library_install_command, libraries_import, missing_from_exe
from babysitter.plugins.voice.keyword import stage_vosk_libraries

ROOT = Path(__file__).resolve().parents[1]
_original_import = __import__


def _raising(name, message):
    def broken(imported, globals=None, locals=None, fromlist=(), level=0):
        if imported == name:
            raise FileNotFoundError(message)
        return _original_import(imported, globals, locals, fromlist, level)

    return broken


def test_a_missing_kokoro_config_leaves_the_voice_off(monkeypatch):
    monkeypatch.setattr(
        "builtins.__import__",
        _raising(
            "kokoro_onnx",
            r"C:\Users\Michele\AppData\Local\Temp\_MEI000115002\kokoro_onnx\config.json",
        ),
    )
    from babysitter.plugins.voice.kokoro_voice import packages_installed

    assert packages_installed() is False


def test_a_missing_hearing_dll_leaves_speech_recognition_off(monkeypatch):
    monkeypatch.setattr(
        "builtins.__import__",
        _raising("faster_whisper", r"C:\Users\Michele\AppData\Local\Temp\_MEI000115002\ctranslate2"),
    )
    from babysitter.plugins.voice.hearing import packages_installed

    assert packages_installed() is False


def test_a_missing_onnx_dll_leaves_the_sharper_memory_off(monkeypatch):
    def broken(imported, globals=None, locals=None, fromlist=(), level=0):
        if imported in {"numpy", "onnxruntime"}:
            raise FileNotFoundError(r"C:\Users\Michele\AppData\Local\Temp\_MEI000115002\onnxruntime")
        return _original_import(imported, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", broken)
    from babysitter.embedder import packages_installed

    assert packages_installed() is False


def test_an_ordinary_import_miss_is_still_not_installed(monkeypatch):
    def as_import_error(imported, globals=None, locals=None, fromlist=(), level=0):
        if imported == "kokoro_onnx":
            raise ImportError("No module named kokoro_onnx")
        return _original_import(imported, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", as_import_error)
    assert libraries_import("kokoro_onnx") is False


def test_the_exe_does_not_launch_itself_as_pip(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert library_install_command(("kokoro-onnx==0.6.1",)) is None
    text = missing_from_exe("Heart and Sarah")
    assert "BabySitter.exe" in text
    assert "Nothing was downloaded." in text

    from babysitter.plugins.voice.kokoro_voice import KokoroError, download

    monkeypatch.setattr("babysitter.plugins.voice.kokoro_voice.packages_installed", lambda: False)
    called = []
    monkeypatch.setattr(
        "babysitter.plugins.voice.kokoro_voice.run_hidden",
        lambda *args, **kwargs: called.append(args),
    )
    try:
        download()
    except KokoroError as exc:
        assert "BabySitter.exe" in str(exc)
    else:
        raise AssertionError("The exe should refuse to pip-install.")
    assert called == []


def test_a_source_run_still_has_a_pip_command():
    command = library_install_command(("vosk==0.3.45",))
    assert command is not None
    assert command[1:3] == ["-m", "pip"]
    assert "vosk==0.3.45" in command


def test_libvosk_at_the_temp_root_is_copied_into_the_vosk_folder(tmp_path):
    (tmp_path / "libvosk.dll").write_bytes(b"vosk")
    (tmp_path / "libgcc_s_seh-1.dll").write_bytes(b"gcc")
    (tmp_path / "Qt6Core.dll").write_bytes(b"qt")
    stage_vosk_libraries(str(tmp_path))
    assert (tmp_path / "vosk" / "libvosk.dll").read_bytes() == b"vosk"
    assert (tmp_path / "vosk" / "libgcc_s_seh-1.dll").read_bytes() == b"gcc"
    assert not (tmp_path / "vosk" / "Qt6Core.dll").exists()


def test_a_vosk_folder_that_already_has_the_library_is_left_alone(tmp_path):
    folder = tmp_path / "vosk"
    folder.mkdir()
    (folder / "libvosk.dll").write_bytes(b"already")
    (tmp_path / "libvosk.dll").write_bytes(b"other")
    stage_vosk_libraries(str(tmp_path))
    assert (folder / "libvosk.dll").read_bytes() == b"already"


def test_no_vosk_library_does_not_invent_a_folder(tmp_path):
    stage_vosk_libraries(str(tmp_path))
    assert not (tmp_path / "vosk").exists()


def test_the_exe_build_packs_the_files_those_libraries_open():
    text = (ROOT / "packaging" / "babysitter.spec").read_text(encoding="utf-8")
    for name in (
        "kokoro_onnx",
        "espeakng_loader",
        "_sounddevice_data",
        "vosk",
        "faster_whisper",
        "onnxruntime",
    ):
        assert f'"{name}"' in text
    assert "collect_data_files" in text
    assert "collect_dynamic_libs" in text
    voice = (ROOT / "requirements-voice.txt").read_text(encoding="utf-8")
    assert "kokoro-onnx==0.6.1" in voice
    assert "vosk==0.3.45" in voice
    build = (ROOT / "scripts" / "build-exe.bat").read_text(encoding="utf-8")
    assert "requirements-voice.txt" in build
