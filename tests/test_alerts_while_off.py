"""NEXT_ROUND phase 5: new mail and events said while the AI is off."""

from datetime import datetime

from babysitter.quiet import alerts_silenced


def test_quiet_hours_and_the_night_silence_alerts():
    noon = datetime(2026, 11, 27, 12, 0)
    late = datetime(2026, 11, 27, 23, 30)
    early = datetime(2026, 11, 27, 6, 0)
    assert not alerts_silenced(False, "22:00", "07:00", noon)
    assert alerts_silenced(False, "22:00", "07:00", late)  # quiet hours off: the night still counts
    assert alerts_silenced(False, "22:00", "07:00", early)
    assert alerts_silenced(True, "12:00", "13:00", noon)  # your own quiet hours win
    assert not alerts_silenced(True, "12:00", "13:00", late)


def _shell(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    return app, controller, shell


def test_new_mail_is_said_in_the_windows_voice_while_off(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    try:
        controller.settings.google_enabled = True
        controller.settings.alerts_when_off = True
        controller.power.state = "off"
        monkeypatch.setattr("babysitter.quiet.alerts_silenced", lambda *a, **k: False)
        started: list = []
        monkeypatch.setattr(shell, "_start_google", lambda kind, **kw: started.append(kw))
        monkeypatch.setattr(shell, "_warn_google_week", lambda: None)
        spoken: list = []
        monkeypatch.setattr(shell, "_speak", lambda text, **kw: spoken.append((text, kw)))

        shell._sync_off_alerts()
        assert shell._off_poll.isActive()
        shell._check_while_off()
        assert started == [{"speak_errors": False, "only_new": True}]
        shell._google_poll_ready("New from Google: a mail from Sam.", ["id1"])
        assert spoken == [("New from Google: a mail from Sam.", {"alert": True, "windows_only": True})]
        assert controller.state == "off"  # nothing was loaded

        # Game mode does not silence them; the AI being on hands them to the normal check.
        controller.power.state = "game"
        shell._sync_off_alerts()
        assert shell._off_poll.isActive()
        controller.power.state = "on"
        shell._sync_off_alerts()
        assert not shell._off_poll.isActive()

        # Turned off in Settings: no reads at all.
        controller.power.state = "off"
        shell._set_alerts_when_off(False)
        assert not shell._off_poll.isActive()
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()


def test_quiet_hours_skip_the_read_entirely(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    try:
        controller.settings.google_enabled = True
        controller.power.state = "off"
        monkeypatch.setattr("babysitter.quiet.alerts_silenced", lambda *a, **k: True)
        started: list = []
        monkeypatch.setattr(shell, "_start_google", lambda kind, **kw: started.append(kw))
        shell._check_while_off()
        assert started == []
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()


def test_outlook_alone_is_still_read(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    try:
        controller.settings.google_enabled = False
        monkeypatch.setattr(shell, "_microsoft_accounts", lambda: ["outlook"])
        assert shell._linked_accounts() == ["outlook"]
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()
