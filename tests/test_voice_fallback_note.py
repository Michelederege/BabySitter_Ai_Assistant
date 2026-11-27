"""Long run, scan N (0.29.0): when Kokoro stands in for a natural voice or
your own, the reason is shown. `engines.fallback_note` kept it, but nothing
ever read it."""

from __future__ import annotations


def test_the_reason_kokoro_spoke_is_shown_once(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.plugins.voice import engines
    from babysitter.ui.shell import Shell

    shell = Shell(Controller())
    try:
        monkeypatch.setattr(shell, "_open_followup", lambda: None)
        why = "The natural voice needs about 4 GB of video memory and only 2,100 MB is free, so Kokoro speaks instead."
        engines._fallback_said["note"] = why
        shell._speak_done()
        assert shell.controller.history.count(why) == 1
        assert engines.fallback_note() == "", "the note is read once"
        engines._fallback_said["note"] = why
        shell._speak_done()
        assert shell.controller.history.count(why) == 1, "the same reason is not repeated in one run"
    finally:
        engines._fallback_said["note"] = ""
        shell.window.close()
