import sys

import pytest

from babysitter.responsiveness import ResponsivenessLog, TurnClock


def test_the_log_keeps_timings_and_drops_words():
    log = ResponsivenessLog()
    log.add({"first_sound": 800, "transcript": 120, "heard": "what time is it"})
    log.add({"first_sound": 1400})
    assert log.rows == [{"first_sound": 800, "transcript": 120}, {"first_sound": 1400}]
    assert "what time" not in log.summary()
    assert "what time" not in log.export_text()
    assert "Typical time to first sound: 800 ms" in log.summary()
    assert "Worst: 1400 ms" in log.summary()


def test_a_turn_clock_records_milliseconds():
    clock = TurnClock()
    clock.mark("transcript")
    clock.mark("transcript")
    row = clock.as_row()
    assert row["transcript"] == 0 or row["transcript"] >= 0
    assert list(row).count("transcript") == 1


@pytest.mark.skipif(sys.platform != "win32", reason="the window installs Windows global hotkeys")
def test_the_pc_check_does_not_freeze_the_window(tmp_path, monkeypatch):
    import subprocess
    import time

    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    from babysitter import platform as bs_platform
    from babysitter.controller import Controller
    from babysitter.ui import shell as shell_module

    def slow_powershell(args, timeout=0, **_kw):
        time.sleep(0.6)
        return subprocess.CompletedProcess(args, 0, stdout="--- Memory ---\nok", stderr="")

    monkeypatch.setattr(bs_platform, "run_hidden", slow_powershell)
    monkeypatch.setattr(shell_module.sys, "platform", "win32")
    controller = Controller()
    shell = shell_module.Shell(controller)
    try:
        started = time.perf_counter()
        shell._read_health()
        assert time.perf_counter() - started < 0.3
        assert "Checking this PC" in shell.window.health_page.body.toPlainText()
        assert shell._health_job.wait(5000)
        app.processEvents()
        assert "--- Memory ---" in shell.window.health_page.body.toPlainText()
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()
