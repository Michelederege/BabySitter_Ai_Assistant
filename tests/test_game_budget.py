"""Fitting the AI beside a game, by the memory the game leaves."""

from types import SimpleNamespace

from babysitter.gamebudget import CLOSED_READINGS, SETTLE_READINGS, GameBudget, fitting_level, room_mib
from babysitter.intelligence import MODES

TOTAL = 12282
LOW = MODES["low"].vram_mib
MEDIUM = MODES["medium"].vram_mib
GB = 1024 ** 3


def _run(budget, readings, **fixed):
    actions = []
    for _ in range(readings):
        actions.append(budget.decide(**fixed))
    return actions


def test_room_does_not_count_babysitters_own_model():
    # 11 GB in use, 7.5 GB of it is the loaded model: the game holds 3.5 GB.
    assert room_mib(TOTAL, 11000, 7500) == TOTAL - 3500
    assert fitting_level("medium", TOTAL) == "medium"
    assert fitting_level("medium", LOW) == "low"
    assert fitting_level("medium", LOW - 1) is None
    assert fitting_level("low", TOTAL) == "low"


def test_a_light_game_changes_nothing():
    budget = GameBudget()
    fixed = dict(game="stardew.exe", state="on", chosen="medium", loaded="medium",
                 gpu=(TOTAL, MEDIUM + 1500, MEDIUM), ram_free=8 * GB)
    assert all(a.kind == "none" for a in _run(budget, 10, **fixed))


def test_a_heavy_game_switches_medium_to_low_after_it_settles():
    budget = GameBudget()
    game_mib = TOTAL - LOW  # exactly room for Low, not for Medium
    fixed = dict(game="bg3.exe", state="on", chosen="medium", loaded="medium",
                 gpu=(TOTAL, game_mib + MEDIUM, MEDIUM), ram_free=8 * GB)
    actions = _run(budget, SETTLE_READINGS, **fixed)
    assert [a.kind for a in actions[:-1]] == ["none"] * (SETTLE_READINGS - 1)
    assert actions[-1].kind == "lower" and actions[-1].level == "low"
    assert budget.restore_to == "medium"


def test_one_spike_does_not_switch():
    budget = GameBudget()
    heavy = dict(game="bg3.exe", state="on", chosen="medium", loaded="medium",
                 gpu=(TOTAL, TOTAL, MEDIUM), ram_free=8 * GB)
    light = dict(heavy, gpu=(TOTAL, MEDIUM + 500, MEDIUM))
    for _ in range(5):
        assert budget.decide(**heavy).kind == "none"
        assert budget.decide(**light).kind == "none"


def test_nothing_fits_means_game_mode_and_it_ends_when_the_game_closes():
    budget = GameBudget()
    fixed = dict(game="cyberpunk.exe", state="on", chosen="medium", loaded="low",
                 gpu=(TOTAL, (TOTAL - LOW + 2000) + LOW, LOW), ram_free=8 * GB)
    actions = _run(budget, SETTLE_READINGS, **fixed)
    assert actions[-1].kind == "game"
    # The controller records game mode only once it really switches.
    budget.entered_game("medium")
    closed = dict(fixed, game=None, state="game", gpu=(TOTAL, 1500, 0))
    actions = _run(budget, CLOSED_READINGS, **closed)
    assert actions[-1].kind == "leave_game"
    assert budget.auto_game is False


def test_the_chosen_level_comes_back_when_the_game_closes():
    budget = GameBudget()
    budget.restore_to = "medium"
    closed = dict(game=None, state="on", chosen="medium", loaded="low",
                  gpu=(TOTAL, 2000, LOW), ram_free=8 * GB)
    actions = _run(budget, CLOSED_READINGS, **closed)
    assert [a.kind for a in actions[:-1]] == ["none"] * (CLOSED_READINGS - 1)
    assert actions[-1].kind == "restore" and actions[-1].level == "medium"
    assert budget.restore_to == ""


def test_the_level_never_goes_up_while_the_game_runs():
    budget = GameBudget()
    budget.restore_to = "medium"
    roomy = dict(game="bg3.exe", state="on", chosen="medium", loaded="low",
                 gpu=(TOTAL, LOW + 500, LOW), ram_free=8 * GB)
    assert all(a.kind == "none" for a in _run(budget, 10, **roomy))


def test_low_system_memory_counts_as_no_room():
    budget = GameBudget()
    fixed = dict(game="bg3.exe", state="on", chosen="low", loaded="low",
                 gpu=(TOTAL, LOW + 500, LOW), ram_free=GB // 2)
    assert _run(budget, SETTLE_READINGS, **fixed)[-1].kind == "game"


def test_after_leave_a_game_can_lower_but_never_unload():
    budget = GameBudget()
    fixed = dict(game="bg3.exe", state="on", chosen="low", loaded="low",
                 gpu=(TOTAL, TOTAL, LOW), ram_free=8 * GB, may_unload=False)
    assert all(a.kind == "none" for a in _run(budget, 10, **fixed))


def test_a_choice_by_hand_is_not_undone():
    budget = GameBudget()
    budget.entered_game("medium")
    budget.forget()
    closed = dict(game=None, state="game", chosen="medium", loaded="medium",
                  gpu=(TOTAL, 1500, 0), ram_free=8 * GB)
    assert all(a.kind == "none" for a in _run(budget, 10, **closed))


def _controller(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.controller import Controller

    controller = Controller()
    calls: list[tuple] = []
    monkeypatch.setattr(controller, "reload_model", lambda level=None: calls.append(("reload", level)))
    monkeypatch.setattr(controller, "enter_game", lambda auto=False: calls.append(("game", auto)))
    controller.power.state = "on"
    controller.loaded_level = "medium"
    controller.settings.auto_game_mode = True
    controller.settings.game_mode_ask = False
    controller.settings.game_processes = ["bg3.exe"]
    return controller, calls


def _snap(used, ours, games=("bg3.exe",)):
    return SimpleNamespace(
        gpu=SimpleNamespace(total_mib=TOTAL, used_mib=used, ollama_mib=ours),
        ram_total_bytes=32 * GB, ram_used_bytes=16 * GB,
        process_names=set(games), detected_game=None,
    )


def test_the_controller_switches_down_and_waits_for_a_reply(tmp_path, monkeypatch):
    controller, calls = _controller(tmp_path, monkeypatch)
    heavy = _snap((TOTAL - LOW) + MEDIUM, MEDIUM)
    busy = {"now": True}
    controller.reply_busy = lambda: busy["now"]
    for _ in range(SETTLE_READINGS + 2):
        controller._on_status(heavy)
    assert calls == []  # an answer is still being spoken
    busy["now"] = False
    for _ in range(SETTLE_READINGS):
        controller._on_status(heavy)
    assert calls == [("reload", "low")]


def test_on_with_a_heavy_game_loads_the_level_that_fits(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.controller import Controller

    controller = Controller()
    jobs: list[tuple] = []
    monkeypatch.setattr(controller.worker, "submit", jobs.append)
    controller.settings.auto_game_mode = True
    controller.settings.intelligence = "medium"
    controller.settings.game_processes = ["bg3.exe"]
    controller.latest_status = _snap(TOTAL - LOW, 0)
    controller.turn_on()
    assert jobs[-1][0] == "on" and jobs[-1][1] == MODES["low"].model and jobs[-1][3] is None
    assert controller.budget.restore_to == "medium"
    assert controller.settings.intelligence == "medium"  # your choice is not overwritten


def test_leave_cancels_an_old_load_the_brain_timer(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    try:
        monkeypatch.setattr(controller, "wake", lambda: None)
        controller.power.state = "on"
        shell._return_to_game = True
        shell._arm_game_return()
        assert shell._game_return_timer.isActive()
        controller.power.state = "game"
        shell._on_game()  # Leave
        assert shell._return_to_game is False
        assert not shell._game_return_timer.isActive()
        # A timer that fires during an answer waits instead of unloading.
        entered: list = []
        monkeypatch.setattr(controller, "enter_game", lambda auto=False: entered.append(auto))
        controller.power.state = "on"
        shell._return_to_game = True
        shell._speaking = True
        shell._return_game_now()
        assert entered == [] and shell._game_return_timer.isActive()
        shell._speaking = False
        shell._game_return_timer.stop()
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()
