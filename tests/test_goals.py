"""Goals on the Reminders page, spoken the way a short conversation goes."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _shell(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    monkeypatch.setattr(shell, "_speak", lambda *_args, **_kwargs: None)
    return app, controller, shell


def _close(app, controller, shell):
    shell.registrar.clear()
    controller.shutdown_threads()
    app.processEvents()


def test_saying_my_goals_shows_the_list_on_the_reminders_page(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    page = shell.window.schedule_page
    assert page.goals.item(0).text() == "No goals yet."

    page.goal_text.setText("Finish the bracket")
    page._add_goal()
    app.processEvents()
    # v3: the goals are on the Board.
    assert shell.window.current_page() is shell.window.home.pin_card
    assert page.goals.item(0).text() == "1. Finish the bracket"
    assert "Finish the bracket" in shell.window.home.spoken.text()
    assert shell.window.home.reply_detail.text() == "1. Finish the bracket"

    shell._run_quick("add another to call Mom")
    assert page.goals.item(1).text() == "2. call Mom"
    shell._run_quick("say my goals")
    assert "finish the bracket" in shell.window.home.spoken.text().lower()
    assert "call Mom" in shell.window.home.spoken.text()
    assert shell.window.nav_group.button(1).isChecked()

    page.goals.setCurrentRow(1)
    page._done_goal()
    app.processEvents()
    assert page.goals.item(0).text() == "1. Finish the bracket"
    assert page.goals.item(1).text() == "Done. call Mom"

    page.text.setText("stretch")
    page.when.setText("in 20 minutes")
    page._add()
    app.processEvents()
    from babysitter.deskstore import load_list

    assert load_list("schedule.json")[-1]["text"] == "stretch"
    assert "stretch" in page.list.item(0).text()
    assert load_list("goals.json")[0]["text"] == "Finish the bracket"
    assert "stretch" not in page.goals.item(0).text()
    _close(app, controller, shell)


def test_a_goal_talk_closes_and_other_commands_stay_themselves(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    shell._run_quick("add a goal to finish the bracket")
    shell._run_quick("add another to water the plants")
    assert shell._goals_open is True
    assert shell._run_quick("and also check my email") is False
    from babysitter.deskstore import load_list

    assert [item["text"] for item in load_list("goals.json")] == [
        "finish the bracket",
        "water the plants",
    ]
    assert shell._goals_open is False

    shell._run_quick("say my goals")
    assert shell._run_quick("open the second one") is True
    assert [item["done"] for item in load_list("goals.json")] == ["", ""]
    assert shell._goals_open is False

    shell._run_quick("my goals")
    shell._open_followup()
    while shell._followup_left > 0:
        shell._follow_tick()
    assert shell._goals_open is False
    assert shell._run_quick("the second") is False
    assert [item["text"] for item in load_list("goals.json")] == [
        "finish the bracket",
        "water the plants",
    ]
    _close(app, controller, shell)
