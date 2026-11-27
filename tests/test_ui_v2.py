"""The v2 interface: the frog orb, the rail, and the new pages, offscreen."""

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
    return app, controller, shell


def _close(app, controller, shell):
    shell.registrar.clear()
    controller.shutdown_threads()
    app.processEvents()


def test_frog_orb_plays_sprites_and_keeps_short_captions(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from babysitter.ui.orb import Orb

    orb = Orb()
    # The sprite strips ship with the program, one per state.
    assert set(orb._strips) == {
        "off", "working", "on", "listening", "thinking", "speaking", "game", "needs",
    }
    orb.set_state("starting", "Starting Ollama.")
    assert orb.state == "starting"
    assert orb._caption == "Starting Ollama"
    long_detail = "This is a much longer sentence than the caption pill under the frog could hold."
    orb.set_state("error", long_detail)
    assert orb._caption == "Needs you"
    assert orb.toolTip() == long_detail
    app.processEvents()



def test_six_places_replace_the_twelve_pages(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    window = shell.window
    labels = [window.nav_group.button(i).property("navLabel") for i in range(6)]
    assert labels == ["Talk", "Board", "Today", "Desk", "Memory", "Settings"]
    # Every old page still opens, in its new place.
    for page, place in (
        (window.files_page, "desk"), (window.schedule_page, "today"), (window.history_page, "memory"),
        (window.voice_page, "settings"), (window.health_page, "settings"), (window.models_page, "settings"),
    ):
        window.show_page(page)
        assert window.current_page() is page
        assert window.show_page_key(page) == place
    shell.show_window()
    assert window.current_page() is window.home
    # No Half screen or Full screen buttons any more.
    assert not hasattr(window, "half_button") and not hasattr(window, "full_button")
    _close(app, controller, shell)


def test_the_menu_reflows_from_labels_to_icons_to_a_bottom_bar(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    window = shell.window
    window.show()
    for width, side, bottom, text in ((1180, True, False, "◉  Talk"), (900, True, False, "◉"), (460, False, True, None)):
        window.resize(width, 700)
        app.processEvents()
        assert window.side_menu.isVisible() is side, width
        assert window.bottom_bar.isVisible() is bottom, width
        if text is not None:
            assert window.nav_group.button(0).text() == text
        assert window.stack.currentWidget().horizontalScrollBar().maximum() == 0 if hasattr(window.stack.currentWidget(), "horizontalScrollBar") else True
    _close(app, controller, shell)


def test_journal_and_files_pages_drive_the_same_quick_commands(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    spoken: list[str] = []
    monkeypatch.setattr(shell, "_speak", spoken.append)

    journal = shell.window.journal_page
    journal.task_name.setText("sanding the door")
    journal._start_task()
    assert "Started sanding the door" in spoken[-1]
    journal.notice.emit("TASK done")
    assert "sanding the door took" in spoken[-1]
    journal.notice.emit("JOURNAL today")
    assert spoken[-1]

    files = shell.window.files_page
    prints = tmp_path / "prints"
    prints.mkdir()
    (prints / "helmet.stl").write_text("solid", encoding="utf-8")
    controller.settings.search_folders = [str(prints)]
    shell._fill_settings()
    assert str(prints) in files.folders_line.text()
    files.query.setText("helmet stl")
    files._find()
    job = shell._find_job
    assert job.wait(5000)
    app.processEvents()
    assert "helmet.stl" in files.body.toPlainText()
    _close(app, controller, shell)


def test_pin_cards_build_and_unpin(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    shell._last_reply = ("The time", "It's Tuesday, 3 PM.")
    shell._pin_reply()
    app.processEvents()
    from babysitter.deskstore import load_list

    pins = load_list("pins.json")
    assert len(pins) == 1
    assert shell.window.home.pin_count.text() == "1 of 12"
    shell._unpin_card(str(pins[0]["id"]))
    assert load_list("pins.json") == []
    assert shell.window.home.pin_count.text() == "0 of 12"
    _close(app, controller, shell)


def test_a_typed_note_pins_and_a_reminder_shows_its_clock(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    home = shell.window.home
    home.pin_title.setText("Bins")
    home.pin_body.setText("Thursday")
    home._submit_pin()
    app.processEvents()
    from babysitter.deskstore import add_item, load_list

    pins = load_list("pins.json")
    assert pins[0]["title"] == "Bins"
    assert pins[0]["body"] == "Thursday"
    assert home.pin_title.text() == ""
    add_item("schedule.json", text="go to bed", due="2026-11-15T13:30", fired="")
    page = shell.window.schedule_page
    page.refresh()
    shown = page.list.item(0).text()
    assert "go to bed" in shown
    assert "01:30" not in shown
    assert "1:30" in shown
    assert shell.window.nav_group.button(2).property("navLabel") == "Today"
    assert shell.window.home.game.text() == "Game mode"
    assert shell.window.settings_page.game_mode_ask.isChecked() is False
    _close(app, controller, shell)


def test_adding_a_reminder_keeps_the_time_and_a_pin_saves_it(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    monkeypatch.setattr(shell, "_speak", lambda *_args, **_kwargs: None)
    page = shell.window.schedule_page
    page.text.setText("stretch")
    page.when.setText("in 20 minutes")
    page._add()
    app.processEvents()
    from babysitter.deskstore import load_list

    saved = load_list("schedule.json")
    assert saved[-1]["text"] == "stretch"
    assert saved[-1]["due"]
    page.refresh()
    button = page.list.findChild(type(shell.window.home.hold))
    pins = page.list.findChildren(type(shell.window.home.hold))
    assert pins
    pins[0].click()
    app.processEvents()
    cards = load_list("pins.json")
    assert cards
    assert "stretch" in (cards[-1]["body"] + cards[-1]["title"]).lower()
    _close(app, controller, shell)


def test_a_spoken_timer_is_a_reminder(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    monkeypatch.setattr(shell, "_speak", lambda *_args, **_kwargs: None)
    shell._run_quick("set a timer for 5 minutes to check the oven")
    from babysitter.deskstore import load_list

    saved = load_list("schedule.json")
    assert saved[-1]["text"] == "check the oven"
    assert saved[-1]["due"]
    assert shell._active_timer is not None
    _close(app, controller, shell)


def test_a_long_reminder_row_grows_when_the_line_wraps(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    from babysitter.deskstore import add_item

    add_item(
        "schedule.json",
        text="stretch before the long meeting down the hall and bring the notes",
        due="2026-11-16T18:00:00",
        fired="",
    )
    page = shell.window.schedule_page
    page.list.setFixedWidth(180)
    page.refresh()
    app.processEvents()
    assert page.list.item(0).sizeHint().height() > 40
    _close(app, controller, shell)


def test_home_shows_the_countdown_for_a_new_reminder(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    from datetime import datetime, timedelta

    from babysitter.deskstore import add_item

    moment = datetime.now().astimezone() + timedelta(minutes=20)
    add_item("schedule.json", text="stretch", due=moment.isoformat(timespec="seconds"), fired="")
    shell.window.schedule_page.refresh()
    shell._show_reminder_clock()
    assert "stretch" in shell.window.home.countdown.text()
    assert "—" in shell.window.home.countdown.text()
    assert "stretch" in shell.window.schedule_page.list.item(0).text()
    _close(app, controller, shell)


def test_a_due_reminder_rings_while_the_ai_is_off(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    assert controller.state == "off"
    from datetime import datetime, timedelta

    from babysitter.deskstore import add_item, load_list

    moment = datetime.now().astimezone() - timedelta(minutes=1)
    add_item("schedule.json", text="stretch", due=moment.isoformat(timespec="seconds"), fired="")
    spoken = []
    monkeypatch.setattr(shell, "_speak", lambda text, **kwargs: spoken.append((text, kwargs)))
    notes = []
    monkeypatch.setattr(shell.tray, "notify", lambda title, body: notes.append((title, body)))
    shell._check_reminders()
    assert load_list("schedule.json")[0]["fired"] == "yes"
    assert spoken[0][0] == "Reminder. stretch"
    assert spoken[0][1]["alert"] is True
    assert notes[0][0] == "Reminder"
    assert controller.state == "off"
    _close(app, controller, shell)


def test_a_clock_answer_stays_in_the_conversation(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    monkeypatch.setattr(shell, "_speak", lambda *_args, **_kwargs: None)
    shell._logged_turn = True
    shell._run_quick("what time is it")
    assert shell._history[-2]["role"] == "user"
    assert shell._history[-2]["content"] == "what time is it"
    assert "It's" in shell._history[-1]["content"]
    _close(app, controller, shell)


def test_listening_shows_on_the_state_pill(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    shell._keyword_status("capturing")
    assert shell.window.pill.text() == "Listening"
    assert shell.window.title_word.text() == "Listening"
    assert shell.orb.state == "listening"
    shell._keyword_status("waiting")
    assert shell.window.pill.text() == "On"
    assert shell.orb.state == "on"
    shell._show_mode("thinking", "Thinking.")
    assert shell.window.pill.text() == "Thinking"
    shell._show_mode("speaking", "Speaking the answer.")
    assert shell.window.pill.text() == "Speaking"
    shell._on_state("on", "The AI is on.")
    assert shell.window.pill.text() == "On"
    _close(app, controller, shell)


def test_the_home_picture_fills_the_panel_and_follows_the_state(tmp_path, monkeypatch):
    app, _controller, shell = _shell(tmp_path, monkeypatch)
    home = shell.window.home
    # v3: the pond picture follows the window height, 118 px when short.
    home.hero.set_window_height(600)
    assert home.hero.height() == 118
    home.hero.set_window_height(800)
    assert home.hero.height() == 190
    home.hero.set_window_height(2000)
    assert home.hero.height() == 260
    home.set_phase("off", "The AI is off. Nothing is listening.")
    assert home.phase_word.text() == "Off"
    assert home.hero.frog._state == "off"
    home.set_phase("on", "Hold Mouse 4 or say the keyword.")
    assert home.hero._key == "on"
    assert home.phase_hint.text() == "Hold Mouse 4 or say the keyword."
    picture = next(
        child for child in home.hero.findChildren(type(home.hold)) if child.text() == "Choose my picture"
    )
    assert picture.parent() is home.hero
    _close(app, _controller, shell)



def test_the_state_menu_holds_power_intelligence_game_and_the_keyword(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    window = shell.window
    window.show()
    window.resize(460, 640)
    app.processEvents()
    home = window.home
    menu = window._state_menu
    for control in (home.power, home.keyword_button, home.keyword_edit, home.game, home.reload):
        assert menu.isAncestorOf(control)
    window.pill.click()
    app.processEvents()
    assert menu.isVisible()
    assert controller.state == "off"  # opening the menu does not turn anything on
    menu.hide()
    # The Talk page never scrolls sideways in a narrow window.
    scroll = window.stack.currentWidget()
    assert scroll.horizontalScrollBar().maximum() == 0
    _close(app, controller, shell)


def test_the_state_pill_and_status_line_follow_the_controller(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    shell._on_state("game", "The model is unloaded for a game.")
    assert shell.window.pill.text() == "Game"
    assert "unloaded for a game" in shell.window.status_line.text()
    assert shell.window.title_word.text() == "Game"
    # The top-bar privacy word flips while an outside tool is on.
    controller.settings.google_enabled = True
    shell._refresh_privacy()
    assert shell.window.privacy_chip.text() == "Online only when you approve"
    controller.settings.google_enabled = False
    shell._refresh_privacy()
    assert shell.window.privacy_chip.text() == "Private to this computer"
    _close(app, controller, shell)


def test_talk_folds_details_and_fresh_start_keeps_pins(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    home = shell.window.home
    home.set_reply("what is on my desk", "Three files.", "1. a.pdf\n2. b.stl")
    assert not home.reply_detail.isVisible() and not home.details_button.isHidden()
    shell.window.show()
    home._toggle_details()
    assert home.reply_detail.isVisible() and home.details_button.text() == "Hide details"
    home.set_reply("time", "It's noon.", "")
    assert home.details_button.isHidden()
    shell._history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    shell._pin_note("Bins", "Thursday")
    home.fresh_start.emit()
    assert shell._history == []
    assert "Fresh start" in home.spoken.text()
    from babysitter.deskstore import load_list

    assert load_list("pins.json")  # pins stay
    assert home.hold.text() == "Turn the AI on"  # the AI is off
    _close(app, controller, shell)


def test_the_board_filters_locks_and_undoes_an_unpin(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    from babysitter.deskstore import load_list

    home = shell.window.home
    shell._pin_note("Bins", "Thursday")
    shell._pin_note("Groceries", "1. eggs 2. milk")
    pins = load_list("pins.json")
    assert [pin["kind"] for pin in pins] == ["note", "list"] and all(pin.get("pinned") for pin in pins)
    home._set_filter("list")
    assert len(home.pin_grid._items) == 1
    home._set_filter("all")
    assert len(home.pin_grid._items) == 2
    bins = pins[0]["id"]
    shell._lock_pin(bins, True)
    shell._unpin_card(bins)
    assert len(load_list("pins.json")) == 2  # a locked card stays
    shell._lock_pin(bins, False)
    shell._unpin_card(bins)
    assert [pin["title"] for pin in load_list("pins.json")] == ["Groceries"]
    assert not home.undo_strip.isHidden()
    home._undo_unpin()
    assert sorted(pin["title"] for pin in load_list("pins.json")) == ["Bins", "Groceries"]
    _close(app, controller, shell)


def test_frog_strips_are_shared_and_decoded_on_first_use():
    QApplication.instance() or QApplication([])
    from babysitter.paths import asset_path
    from babysitter.ui.hero_banner import FrogSprite
    from babysitter.ui.orb import Orb
    from babysitter.ui.sprites import FrogStrips, frog_strips

    fresh = FrogStrips(asset_path("orb"))
    assert fresh.loaded_states() == []  # nothing decoded until a state is drawn
    assert fresh.get("off")[1] > 0
    assert fresh.loaded_states() == ["off"]
    orb = Orb()
    picture = FrogSprite(asset_path("orb"))
    assert orb._strips is picture._strips is frog_strips(asset_path("orb"))  # one copy for both frogs
    assert fresh.get("no such state") is None
