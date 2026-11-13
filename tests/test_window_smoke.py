"""Builds the window without showing it on a real desktop."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def test_home_window_builds_off_and_has_the_power_button(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    shell.show()
    app.processEvents()
    assert controller.state == "off"
    assert shell.window.home.power.state == "off"
    assert shell.window.windowTitle() == "BabySitter"
    assert "Start BabySitter when I sign in" in shell.window.settings_page.autostart.text()
    assert shell.window.settings_page.autostart.isChecked() is False
    assert shell.window.tools_page.enabled.isChecked() is False
    assert "Private to this computer" in shell.window.home.privacy.text()
    assert "does not send usage data" in shell.window.home.privacy.text()
    shell.window.tools_page.enabled.setChecked(True)
    app.processEvents()
    saved = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert '"social_search_enabled": true' in saved
    shell.registrar.clear()
    controller.shutdown_threads()
    app.processEvents()
