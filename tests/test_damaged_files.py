"""Long run, scan O (0.29.0): damaged data files never stop the window opening.

A voice.json of binary garbage, or valid JSON of the wrong shape (a list),
crashed the Voice page while the window was built, so BabySitter did not
open at all. Every one of its own files is damaged four ways here.
"""

from __future__ import annotations

import pytest

from babysitter.paths import read_json_dict

DAMAGE = {
    "text": b"{not json at all",
    "binary": bytes(range(256)) * 4,
    "empty": b"",
    "wrongshape": b'[1, 2, null, "x"]',
}
FILES = ["settings.json", "voice.json", "schedule.json", "goals.json", "memory.json", "persona.json",
         "ratings.json", "window-geometry.bin", "models/own-voice/own-voice.json"]


@pytest.mark.parametrize("kind", sorted(DAMAGE))
def test_reading_a_damaged_settings_file_gives_nothing(tmp_path, kind):
    path = tmp_path / "voice.json"
    path.write_bytes(DAMAGE[kind])
    assert read_json_dict(path) == {}
    assert read_json_dict(tmp_path / "missing.json") == {}


@pytest.mark.parametrize("kind", sorted(DAMAGE))
def test_the_window_opens_with_every_file_damaged(tmp_path, monkeypatch, kind):
    from PySide6.QtWidgets import QApplication

    for name in FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(DAMAGE[kind])
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    shell = Shell(Controller())
    try:
        spoken = []
        monkeypatch.setattr(shell, "_speak", lambda text, **kw: spoken.append(text))
        for line in ("what time is it", "what's my next reminder", "speak slower", "what do you remember about me"):
            assert shell._run_quick(line) is True
        assert len(spoken) == 4
    finally:
        shell.window.close()
