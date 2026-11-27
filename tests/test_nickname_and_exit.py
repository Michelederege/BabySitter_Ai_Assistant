"""A nickname from one sentence, and no AI left running after BabySitter closes."""

import pytest

from babysitter.commands import match_quick_command
from babysitter.plugins.voice.keyword import command_after_keyword


@pytest.mark.parametrize(
    "said, name",
    [
        ("Call yourself Jarvis", "jarvis"),
        ("I'll call you Jarvis from now on", "jarvis"),
        ("I'm going to call you Friday", "friday"),
        ("From now on your name is Nova", "nova"),
        ("Your nickname is Sunny please", "sunny"),
        ("can I call you Max", "max"),
        ("let's call you Big Mo", "big mo"),
        ("change your name to Pip", "pip"),
    ],
)
def test_one_sentence_sets_the_nickname(said, name):
    quick = match_quick_command(said)
    assert quick is not None and quick.kind == "persona" and quick.detail == name


@pytest.mark.parametrize(
    "said",
    ["I'll call you back", "can I call you later", "be quiet", "call you tomorrow", "be fine"],
)
def test_ordinary_sentences_are_not_names(said):
    quick = match_quick_command(said)
    assert quick is None or quick.kind != "persona"


def test_what_is_your_name_is_answered_here():
    assert match_quick_command("What's your name?").kind == "my_name"


def test_the_nickname_is_saved_and_wakes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.personality import persona_clause, persona_name, save_persona

    save_persona("jarvis")
    assert persona_name() == "Jarvis"
    assert "Your name is Jarvis" in persona_clause()
    assert command_after_keyword("hey jarvis what time is it", "baby sitter") == "what time is it"
    assert command_after_keyword("jarvis", "baby sitter") == ""
    # Only at the start: the name in the middle of a sentence does not wake it.
    assert command_after_keyword("i told jarvis about it", "baby sitter") is None
    assert command_after_keyword("baby sitter open notes", "baby sitter") == "open notes"


def test_closing_stops_the_ollama_babysitter_started(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.controller import Controller

    controller = Controller()
    stopped: list = []
    released: list = []
    monkeypatch.setattr(controller.ollama, "stop_server", lambda: stopped.append(True))
    monkeypatch.setattr("babysitter.plugins.voice.engines.release", lambda: released.append(True))
    controller.ollama.we_started_server = True
    controller.stop_all_ai()
    assert stopped == [True] and released == [True]


def test_a_busy_quit_closes_the_tray_ollama_too(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.controller import Controller

    controller = Controller()
    calls: list = []
    controller._busy = True
    monkeypatch.setattr(controller, "turn_off", lambda **kw: calls.append(kw))
    assert controller.request_quit() == "wait"
    assert calls == [{"emergency": False, "tray_choice": "close"}]


def test_whisper_as_the_old_default_moves_to_moonshine():
    from babysitter.settings import migrate

    assert migrate({"schema_version": 13, "hearing_engine": "whisper"})["hearing_engine"] == "moonshine"
    assert migrate({"schema_version": 13, "hearing_engine": "parakeet"})["hearing_engine"] == "parakeet"


def test_the_model_stays_loaded_while_the_ai_is_on(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    try:
        controller.ollama.we_started_server = True
        assert shell._reply_keep_alive() == -1
        controller.ollama.we_started_server = False
        assert shell._reply_keep_alive() == "30m"
        shell._return_to_game = True
        assert shell._reply_keep_alive() == "2m"
    finally:
        shell._return_to_game = False
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()


def test_no_test_opens_the_real_browser(_never_open_real_files):
    import webbrowser

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl("https://example.com/a"))
    webbrowser.open("https://example.com/b")
    assert _never_open_real_files == ["https://example.com/a", "https://example.com/b"]


def test_a_microphone_that_sends_only_silence_is_named():
    import numpy as np

    from babysitter.plugins.voice.hearing import dead_silence, pcm16_to_wav
    from babysitter.plugins.voice.keyword import SilenceWatch

    zeros = np.zeros(16000 * 2, dtype=np.int16).tobytes()
    room = (np.random.default_rng(1).normal(0, 40, 16000 * 2)).astype(np.int16).tobytes()
    assert dead_silence(pcm16_to_wav(zeros))
    assert not dead_silence(pcm16_to_wav(room))
    assert not dead_silence(pcm16_to_wav(zeros[:3200]))  # a tap on Talk is not a dead mic

    watch = SilenceWatch()
    chunk = np.zeros(1600, dtype=np.int16).tobytes()  # 0.1 s
    fired = [watch.add(chunk) for _ in range(70)]
    assert fired.count(True) == 1 and fired.index(True) == 59
    working = SilenceWatch()
    assert not working.add(room[:3200])
    assert not any(working.add(chunk) for _ in range(100))


def test_google_warns_a_day_before_the_weekly_sign_out():
    from babysitter.plugins.tools.google_account import bundle_from_saved, bundle_text, signout_warning

    day = 86400
    signed = 1_000_000
    bundle = {"access_token": "ya29." + "a" * 30, "refresh_token": "1//" + "r" * 30, "expires_at": 5, "signed_in_at": signed}
    kept = bundle_from_saved(bundle_text(bundle))
    assert kept["signed_in_at"] == signed
    assert signout_warning(kept, now=signed + 3 * day) == ""
    warning = signout_warning(kept, now=signed + 6 * day + 3600)
    assert "sign in again in about 23 hours" in warning
    assert signout_warning(kept, now=signed + 8 * day) == ""  # already ended: the expired notice says so
    assert signout_warning({"access_token": "x"}, now=signed) == ""  # an older sign-in has no date


def test_one_zip_holds_the_memory_and_never_the_sign_ins(tmp_path, monkeypatch):
    import zipfile
    from datetime import datetime

    from babysitter.backup import make_backup

    data = tmp_path / "data"
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(data))
    (data / "journal").mkdir(parents=True)
    (data / "secrets").mkdir()
    (data / "models").mkdir()
    (data / "memory.json").write_text('[{"text": "likes tea"}]', encoding="utf-8")
    (data / "persona.json").write_text('{"name": "Kari"}', encoding="utf-8")
    (data / "journal" / "2026-11-27.json").write_text("[]", encoding="utf-8")
    (data / "secrets" / "google.dpapi").write_bytes(b"locked")
    (data / "models" / "big.onnx").write_bytes(b"x" * 100)
    target, count = make_backup(tmp_path / "out", now=datetime(2026, 11, 27, 3, 4))
    assert target.name == "BabySitter memory 2026-11-27 0304.zip"
    names = set(zipfile.ZipFile(target).namelist())
    assert {"memory.json", "persona.json", "journal/2026-11-27.json", "READ ME.txt"} <= names
    assert count == 3
    assert not any(name.startswith(("secrets/", "models/")) for name in names)
