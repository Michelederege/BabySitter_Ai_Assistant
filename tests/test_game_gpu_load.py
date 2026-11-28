"""0.34.0: how hard a game works the graphics card decides whether BabySitter steps aside."""

from __future__ import annotations

from babysitter.commands import match_quick_command
from babysitter.gamebudget import HEAVY_BUSY, GameBudget, SETTLE_READINGS, card_words
from babysitter.gpuload import Load, load_of, per_engine_busy, per_process_memory
from babysitter.status import StatusSnapshot, probes_paused

ENGINE_ROWS = [
    ("pid_100_luid_0x0_phys_0_eng_0_engtype_3D", 60.0),
    ("pid_100_luid_0x0_phys_0_eng_1_engtype_3D", 30.0),   # same type adds up
    ("pid_100_luid_0x0_phys_0_eng_5_engtype_Copy", 10.0),
    ("pid_200_luid_0x0_phys_0_eng_0_engtype_VideoDecode", 12.0),
    ("not a process row", 99.0),
]


def test_the_busiest_engine_type_is_the_program_load():
    busy = per_engine_busy(ENGINE_ROWS)
    assert busy == {100: 90.0, 200: 12.0}
    memory = per_process_memory([("pid_100_luid_0x0_phys_0", 7.0 * 1024 ** 3), ("pid_100_luid_0x1_phys_0", 1024 ** 2)])
    assert memory == {100: 7169}
    both = load_of({100, 999}, busy, memory)
    assert both == Load(90.0, 7169)


def test_the_snapshot_finds_a_game_by_name():
    snap = StatusSnapshot(0.0, 0, 0, True, pids_by_name={"eldenring.exe": {100, 101}},
                          gpu_loads={100: Load(80.0, 6000), 101: Load(10.0, 500), 300: Load(50.0, 1)})
    load = snap.load_of("EldenRing.exe")
    assert load == Load(90.0, 6500)
    assert StatusSnapshot(0.0, 0, 0, True).load_of("x.exe") is None


def _decide(budget, busy, *, may_unload=True):
    return budget.decide(game="eldenring.exe", state="on", chosen="low", loaded="low",
                         gpu=(12288, 9000, 0), ram_free=8 * 1024 ** 3, may_unload=may_unload, game_busy=busy)


def test_a_game_working_the_card_hard_gets_it_to_itself():
    budget = GameBudget()
    # 9000 of 12288 MB used leaves 3288 MB: Low wouldn't fit anyway, so check a roomy card too.
    roomy = GameBudget()
    actions = [roomy.decide(game="g.exe", state="on", chosen="low", loaded="low", gpu=(24576, 4000, 0),
                            ram_free=8 * 1024 ** 3, game_busy=95.0) for _ in range(SETTLE_READINGS)]
    assert [a.kind for a in actions[:-1]] == ["none"] * (SETTLE_READINGS - 1)
    assert actions[-1].kind == "game" and "95% busy" in actions[-1].reason
    # Below the line, and the memory fits: the AI stays on.
    calm = GameBudget()
    kinds = {calm.decide(game="g.exe", state="on", chosen="low", loaded="low", gpu=(24576, 4000, 0),
                         ram_free=8 * 1024 ** 3, game_busy=HEAVY_BUSY - 20).kind for _ in range(6)}
    assert kinds == {"none"}
    # You woke the model on purpose while the game runs: no unload.
    assert {_decide(budget, 99.0, may_unload=False).kind for _ in range(6)} == {"none"}


def test_a_spike_doesnt_flip_it():
    budget = GameBudget()
    readings = [99.0, 20.0, 99.0, 20.0, 99.0, 20.0]
    kinds = [budget.decide(game="g.exe", state="on", chosen="low", loaded="low", gpu=(24576, 4000, 0),
                           ram_free=8 * 1024 ** 3, game_busy=b).kind for b in readings]
    assert kinds == ["none"] * len(readings)


def test_the_window_being_hidden_no_longer_freezes_the_card_reading():
    assert probes_paused(True, False) is True            # hidden, AI off: rest
    assert probes_paused(True, False, keep_reading=True) is False  # hidden while gaming: keep measuring
    assert probes_paused(False, True, keep_reading=True) is True   # a voice turn still defers it


def test_spoken_words():
    assert card_words("eldenring.exe", 92.4, 7300) == "eldenring.exe is using 92% of the graphics card and 7.1 GB of its memory"
    assert card_words("x.exe", None, 800) == "x.exe is using 800 MB of the graphics card's memory"
    assert "didn't say" in card_words("x.exe", None, None)


def test_asking_how_much_the_game_uses():
    for line in ("how much is the game using", "how busy is my GPU", "what's using my gpu", "should you step aside"):
        said = match_quick_command(line)
        assert said is not None and said.kind == "game_load", line


def test_the_answer_names_the_game_and_the_plan(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    shell = Shell(Controller())
    spoken = []
    monkeypatch.setattr(shell, "_speak", lambda text, *a, **k: spoken.append(text))
    try:
        shell.controller.settings.game_processes = ["eldenring.exe"]
        shell.controller.latest_status = StatusSnapshot(
            0.0, 0, 0, True, process_names={"eldenring.exe"}, pids_by_name={"eldenring.exe": {100}},
            gpu_loads={100: Load(93.0, 7300)},
        )
        shell._run_quick("how much is the game using")
        assert spoken[-1].startswith("eldenring.exe is using 93% of the graphics card and 7.1 GB")
        assert "heavy" in spoken[-1]
        shell.controller.latest_status = StatusSnapshot(0.0, 0, 0, True, gpu_loads={5: Load(1.0, 10)},
                                                        pids_by_name={"dwm.exe": {5}})
        shell._run_quick("how much is the game using")
        assert spoken[-1] == "No game is running, and the graphics card is nearly idle."
    finally:
        shell.window.close()
