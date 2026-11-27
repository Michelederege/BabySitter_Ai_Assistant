"""The double-click starter must show the window and keep a crash visible."""

from pathlib import Path

from babysitter.startup_error import show_startup_failure


ROOT = Path(__file__).resolve().parents[1]


def test_vbs_launcher_shows_the_window():
    text = (ROOT / "Run BabySitter.vbs").read_text(encoding="utf-8")
    assert "pythonw.exe" in text
    assert "shell.Run cmd, 1, False" in text
    assert ", 0," not in text


def test_bat_launcher_stops_and_shows_a_missing_python_folder():
    text = (ROOT / "Run BabySitter.bat").read_text(encoding="utf-8")
    assert "pythonw.exe" in text
    assert "pause" in text
    assert "requirements.txt" in text


def test_startup_failure_is_written(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    # Take the console path. On Windows the real path opens a message box
    # that waits for a click, which stalls the test run on a desktop.
    monkeypatch.setattr("babysitter.startup_error.sys.platform", "linux")
    show_startup_failure("the window toolkit is missing")
    saved = (tmp_path / "logs" / "startup-error.txt").read_text(encoding="utf-8")
    assert saved == "the window toolkit is missing"
    assert "could not start" in capsys.readouterr().err.lower()
