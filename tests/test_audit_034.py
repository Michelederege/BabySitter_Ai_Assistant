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


def test_a_damaged_requests_file_doesnt_stop_babysitter_opening(tmp_path, monkeypatch):
    """"times": "many" in requests.json raised ValueError while the window was built."""
    import json

    from babysitter import wishlist as wl

    (tmp_path / wl.FILE).write_text(json.dumps([{"id": 5, "text": 7, "times": "many"}, {"text": None}, {"id": "a", "text": "ok"}]))
    shell, _spoken = _shell(tmp_path, monkeypatch)
    try:
        shell._run_quick("show my requests")
        rows = [shell.window.requests_list.item(i).text() for i in range(shell.window.requests_list.count())]
        assert rows[0].startswith("1. (empty)") and rows[2].startswith("3. ok")
    finally:
        shell.window.close()


def test_a_list_for_the_intelligence_level_falls_back_to_low(tmp_path):
    import json

    from babysitter.settings import load_settings

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"intelligence": ["high"]}))
    assert load_settings(path).intelligence == "low"


# ---------- hard-bug pass ----------

def test_a_briefly_locked_file_is_still_saved(tmp_path, monkeypatch):
    from pathlib import Path

    from babysitter.privatefile import replace_with_retry

    real = Path.replace
    failures = {"left": 3}

    def flaky(self, target):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError("locked by another program")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    source, target = tmp_path / "a.tmp", tmp_path / "a.json"
    source.write_text("new")
    replace_with_retry(source, target)
    assert target.read_text() == "new"


def test_a_reminder_rings_once_even_when_marking_it_fails(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    import babysitter.ui.shell as shell_module

    shell, spoken = _shell(tmp_path, monkeypatch)
    try:
        past = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(timespec="seconds")
        items = [{"id": "r1", "text": "stretch", "due": past}]

        def broken_save(name, data):
            raise PermissionError("locked")

        monkeypatch.setattr(shell_module, "save_list", broken_save)
        monkeypatch.setattr(shell, "_speak", lambda text, *a, **k: spoken.append(text))
        shell._check_reminders([dict(items[0])])
        shell._check_reminders([dict(items[0])])  # the file still says not rung
        assert sum("stretch" in line for line in spoken) == 1
    finally:
        shell.window.close()


def test_a_stuck_speaking_flag_doesnt_block_reminders(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    shell, spoken = _shell(tmp_path, monkeypatch)
    try:
        shell._speaking = True  # left set by a turn that ended oddly; no voice job runs
        past = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(timespec="seconds")
        shell._check_reminders([{"id": "r2", "text": "drink water", "due": past}])
        assert any("drink water" in line for line in spoken)
    finally:
        shell.window.close()


def test_a_crashed_ollama_is_noticed_and_try_again_can_start_it(tmp_path, monkeypatch):
    """The state stayed On with Ollama gone: every question failed and Try again did nothing."""
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.fixes import fix_for
    from babysitter.power import ERROR, ON
    from babysitter.status import StatusSnapshot

    controller = Controller()
    seen = []
    controller.state_changed.connect(lambda state, message: seen.append((state, message)))
    controller.power.state = ON
    up = StatusSnapshot(0.0, 0, 0, True)
    gone = StatusSnapshot(0.0, 0, 0, False)
    controller._watch_ollama(gone)
    controller._watch_ollama(up)  # one slow reading in between: not a crash
    controller._watch_ollama(gone)
    controller._watch_ollama(gone)
    assert controller.state == ON and not seen
    controller._watch_ollama(gone)
    assert controller.state == ERROR
    assert seen[-1][0] == ERROR and fix_for(seen[-1][1]).action == "retry"
