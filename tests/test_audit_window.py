"""Audit 3 (the window), 0.28.1."""

from __future__ import annotations

from babysitter.status import GpuInfo, StatusSnapshot


def _shell(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    return app, controller, shell


def _snap(names=("explorer.exe",)) -> StatusSnapshot:
    return StatusSnapshot(
        cpu_percent=7.0,
        ram_used_bytes=8 * 1024 ** 3,
        ram_total_bytes=32 * 1024 ** 3,
        port_open=False,
        gpu=GpuInfo(used_mib=900, total_mib=12282, ollama_mib=0),
        process_names=set(names),
    )


def test_the_side_button_check_slows_down_while_it_cannot_be_used(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    try:
        controller.settings.side_button = False
        shell._ptt_tick()
        assert shell._ptt_timer.interval() == 500
        controller.settings.side_button = True
        monkeypatch.setattr(type(controller), "state", property(lambda self: "on"))
        monkeypatch.setattr("ctypes.windll.user32.GetAsyncKeyState", lambda button: 0, raising=False)
        shell._ptt_tick()
        assert shell._ptt_timer.interval() == 40
    finally:
        shell.window.close()


def test_status_updates_keep_no_endless_list(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    try:
        home = shell.window.home
        for _ in range(200):
            home.set_status(_snap())
        assert len(home._vram_samples) == 60
        assert not hasattr(home, "_cpu_samples")
    finally:
        shell.window.close()


def test_the_tray_app_is_noticed_from_one_look(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    try:
        shell._on_status(_snap(("ollama app.exe", "explorer.exe")))
        assert not shell.window.home.tray_banner.isHidden()
        shell._on_status(_snap())
        assert shell.window.home.tray_banner.isHidden()
    finally:
        shell.window.close()


def test_closing_the_natural_voice_waits_two_seconds_at_most(monkeypatch):
    from babysitter.plugins.voice import clone_voice

    waits = []

    class _Slow:
        stdin = None

        def kill(self):
            waits.append("kill")

        def wait(self, timeout=None):
            waits.append(timeout)
            if len(waits) == 1:
                import subprocess

                raise subprocess.TimeoutExpired("helper", timeout)
            return 0

        def poll(self):
            return None

    worker = clone_voice._Worker()
    worker._proc = _Slow()
    worker.stop()
    assert waits[0] == 2 and "kill" in waits
