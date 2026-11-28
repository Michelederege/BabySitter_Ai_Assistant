"""0.34.0 audits 3 to 5: things that broke at the edges."""

from __future__ import annotations

import threading


def _shell(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    shell = Shell(Controller())
    spoken = []
    monkeypatch.setattr(shell, "_speak", lambda text, *a, **k: spoken.append(text))
    return shell, spoken


def test_quit_waits_for_a_running_job_and_says_when_one_wont_stop(tmp_path, monkeypatch):
    """A job still running when Qt tears down aborts the process (a crash box on exit)."""
    from babysitter.ui.shell import _CallJob

    shell, _spoken = _shell(tmp_path, monkeypatch)
    release = threading.Event()
    try:
        quick = _CallJob(lambda: 1)
        shell._store_job("_quick_job", quick)
        quick.start()
        assert shell._settle_threads(2000) is True  # a short job finishes inside the wait

        slow = _CallJob(lambda: release.wait(10))
        shell._store_job("_slow_job", slow)
        slow.start()
        assert shell._settle_threads(100) is False  # quit leaves at once instead of letting Qt abort
    finally:
        release.set()
        slow.wait(3000)
        shell.window.close()
