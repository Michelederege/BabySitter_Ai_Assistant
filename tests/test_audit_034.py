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


def test_look_at_my_screen_with_the_ai_off_says_so(tmp_path, monkeypatch):
    """It crashed: a plain-text box has no append()."""
    shell, spoken = _shell(tmp_path, monkeypatch)
    try:
        assert shell.controller.state != "on"
        shell._look_at_screen()
        assert spoken[-1].startswith("Turn the AI on first")
        assert "Turn the AI on" in shell.window.screen_page.body.toPlainText()
    finally:
        shell.window.close()


def test_back_up_asks_for_a_folder_instead_of_taking_the_click(tmp_path, monkeypatch):
    """clicked(False) was used as the folder: Path(False) raised."""
    from PySide6.QtWidgets import QFileDialog

    shell, _spoken = _shell(tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: asked.append(a) or ""))
    try:
        shell.window.settings_page.backup.click()
        assert len(asked) == 1
    finally:
        shell.window.close()


def test_history_export_and_wipe_finish(tmp_path, monkeypatch):
    """Both did their work, then crashed writing the last line."""
    from babysitter.sessions import append_turn, begin_session

    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        session = begin_session()
        append_turn(session, "hello", "hi there")
        page = shell.window.history_page
        page.refresh()
        page.sessions.setCurrentRow(0)
        assert page.selected_id() == session
        shell._export_session()
        assert "Exported to" in page.body.toPlainText()
        page.wipe_box.setText("WIPE")
        page._wipe()
        assert "Deleted" in page.body.toPlainText()
    finally:
        shell.window.close()
