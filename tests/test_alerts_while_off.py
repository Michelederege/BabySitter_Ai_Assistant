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
        monkeypatch.setattr(shell, "_start_google", lambda kind, **kw: started.append(kw) or True)
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


def test_the_briefing_and_not_saving_conversations(tmp_path, monkeypatch):
    from babysitter.commands import match_quick_command
    from babysitter.deskstore import save_list

    assert match_quick_command("good morning").kind == "briefing"
    assert match_quick_command("brief me").kind == "briefing"
    app, controller, shell = _shell(tmp_path, monkeypatch)
    try:
        spoken: list = []
        monkeypatch.setattr(shell, "_speak", lambda text, **kw: spoken.append(text))
        controller.settings.save_conversations = False
        save_list("goals.json", [{"id": "g1", "text": "finish the essay"}])
        shell._briefing("brief me")
        assert "It's" in spoken[-1] and "1 open goal, starting with finish the essay." in spoken[-1]
        assert "No reminder" not in spoken[-1]

        from babysitter.sessions import list_sessions

        controller.settings.save_conversations = False
        shell._logged_turn = False
        shell._remember_exchange("a private question", "a private answer")
        assert list_sessions() == []
        assert shell._history[-1]["content"] == "a private answer"  # follow-ups still work
        controller.settings.save_conversations = True
        shell._logged_turn = False
        shell._remember_exchange("a saved question", "a saved answer")
        assert len(list_sessions()) == 1
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()


def test_one_mail_check_at_a_time_across_on_and_game(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    try:
        controller.settings.google_enabled = True
        controller.settings.alerts_when_off = True
        started: list = []
        monkeypatch.setattr(shell, "_start_google", lambda kind, **kw: started.append(kw) or True)
        for name in ("_warm_voice", "_warm_hearing", "_arm_game_return", "_sync_keyword"):
            monkeypatch.setattr(shell, name, lambda *a, **k: None)
        controller.power.state = "on"
        shell._on_state("on", "on")
        assert shell._google_poll.isActive() and not shell._off_poll.isActive()
        controller.power.state = "game"
        shell._on_state("game", "game")
        assert not shell._google_poll.isActive() and shell._off_poll.isActive()
        controller.power.state = "on"
        shell._on_state("on", "back from the game")
        assert shell._google_poll.isActive() and not shell._off_poll.isActive()
        assert len(started) == 1  # the first On reads once; the timer does the rest
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()


def test_a_natural_voice_never_takes_the_card_while_off_or_in_a_game(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    try:
        natural = {"engine": "extra", "name": "Narrator: Linda Johnson (LJ Speech)", "speed": 105, "pitch": -1, "label": "x"}
        monkeypatch.setattr("babysitter.ui.shell.kokoro_ready", lambda: True)
        controller.power.state = "on"
        assert shell._off_time_voice(dict(natural)) == natural  # on: the chosen voice
        for state in ("off", "game"):
            controller.power.state = state
            assert shell._off_time_voice(dict(natural))["engine"] == "kokoro"
        monkeypatch.setattr("babysitter.ui.shell.kokoro_ready", lambda: False)
        monkeypatch.setattr("babysitter.plugins.voice.windows_voice.available", lambda: True)
        assert shell._off_time_voice(dict(natural))["engine"] == "windows"
        released: list = []
        monkeypatch.setattr("babysitter.ui.shell.release_kokoro", lambda: released.append("kokoro"))
        shell._release_idle_voices()
        assert released == ["kokoro"]
        controller.power.state = "on"
        shell._release_idle_voices()
        assert released == ["kokoro"]  # on: voices stay warm
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()


def test_the_hidden_orb_stops_animating():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from babysitter.ui.orb import Orb

    orb = Orb()
    orb.show()
    app.processEvents()
    animated = orb._timer.isActive()
    orb.hide()
    app.processEvents()
    assert not orb._timer.isActive()
    orb.show()
    app.processEvents()
    assert orb._timer.isActive() == animated
    orb.close()
