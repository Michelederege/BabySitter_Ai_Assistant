"""The memory slider and the benchmark-only model."""

from babysitter import intelligence
from babysitter.intelligence import CONTEXT_STOPS, MODES, get_mode, level_for_context, set_context


def teardown_function(_fn):
    set_context(0)


def test_each_stop_belongs_to_a_level_that_fits():
    assert [level_for_context(t) for t in CONTEXT_STOPS] == ["low", "medium", "medium", "high", "high"]
    set_context(6144)
    mode = get_mode("medium")
    assert mode.num_ctx == 6144 and mode.model == MODES["medium"].model
    assert get_mode("low").num_ctx == MODES["low"].num_ctx  # other levels keep their own
    set_context(12288)
    assert get_mode("high").num_ctx == 12288
    set_context(5000)  # not a stop
    assert get_mode("medium").num_ctx == MODES["medium"].num_ctx


def test_bonsai_is_only_ever_timed():
    assert "bonsai-2:27b" in intelligence.BENCHMARK_ONLY
    assert all(mode.model != "bonsai-2:27b" for mode in MODES.values())


def test_the_slider_applies_once_on_release_and_a_level_button_resets_it(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.controller import Controller
    from babysitter.settings import load_settings

    controller = Controller()
    reloads: list = []
    monkeypatch.setattr(controller, "reload_model", lambda level=None: reloads.append(level))
    controller.power.state = "on"
    assert controller.set_context(12288) == "high"
    assert reloads == [None]
    saved = load_settings()
    assert (saved.context_tokens, saved.intelligence) == (12288, "high")
    controller.set_intelligence("low")
    assert load_settings().context_tokens == 0 and get_mode("high").num_ctx == MODES["high"].num_ctx


def test_dragging_does_not_reload_until_let_go(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from babysitter.ui.pages.settings_page import SettingsPage

    page = SettingsPage()
    chosen: list = []
    page.context_chosen.connect(chosen.append)
    page.context.setSliderDown(True)
    page.context.setValue(3)
    page.context.setValue(4)
    assert chosen == []  # still dragging
    page.context.setSliderDown(False)  # letting go sends it once
    assert chosen == [16384]
    page.context.setValue(1)  # a key press, not a drag, applies at once
    assert chosen[-1] == 6144
    app.processEvents()


def test_the_benchmark_refuses_other_models_and_drops_bonsai_after(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui import shell as shell_module

    controller = Controller()
    shell = shell_module.Shell(controller)
    try:
        controller.power.state = "on"
        made: list = []
        monkeypatch.setattr(shell_module._BenchJob, "start", lambda job: made.append(job))
        shell._benchmark("some-other:70b")
        assert made == []
        monkeypatch.setattr(controller.ollama, "installed_models", lambda: ["bonsai-2:27b", "qwen3.5:9b"])
        shell._benchmark("bonsai-2:27b")
        assert made and made[-1]._model == "bonsai-2:27b" and made[-1]._keep_alive == 0
        reloads: list = []
        monkeypatch.setattr(controller, "reload_model", lambda level=None: reloads.append(level))
        shell._benchmark_done("Run 1: 900 ms.")
        assert reloads == [None]
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()
