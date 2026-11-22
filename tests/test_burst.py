"""A burst of clicks must not destroy a Qt thread that is still running."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from babysitter.ui.jobs import retain_until_finished, take_turn
from babysitter.ui.pages.desk import SchedulePage


def _app():
    return QApplication.instance() or QApplication([])


class _Tiny(QThread):
    def run(self) -> None:
        return


def test_a_thread_stays_referenced_until_it_finishes():
    app = _app()
    held: list = []
    job = _Tiny()
    retain_until_finished(job, held)
    job.start()
    assert job in held
    assert job.wait(2000)
    app.processEvents()
    assert held == []


def test_a_busy_turn_waits_and_an_idle_turn_starts():
    assert take_turn(True) == "wait"
    assert take_turn(False) == "start"


def test_enter_and_the_button_do_not_save_a_goal_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    _app()
    notes: list[str] = []
    page = SchedulePage()
    page.notice.connect(notes.append)
    page.goal_text.setText("Finish the bracket")
    page._add_goal()
    page.goal_text.setText("Finish the bracket")
    page._add_goal()
    assert notes == ["CONFIRM goal: Finish the bracket"]
    monkeypatch.setattr("babysitter.ui.pages.desk.time.monotonic", lambda: 10)
    page._press_at = {}
    page.goal_text.setText("Ship the build")
    page._add_goal()
    assert notes[-1] == "CONFIRM goal: Ship the build"
