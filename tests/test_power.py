import threading

from babysitter.audio import AudioGate
from babysitter.hotkeys import HotkeyBook
from babysitter.ollama import LoadedModel, OllamaError
from babysitter.power import ERROR, GAME, OFF, ON, PowerService
from babysitter.status import GpuInfo


class FakeOllama:
    def __init__(self) -> None:
        self.port = False
        self.models: list[LoadedModel] = []
        self.started = 0
        self.stopped = 0
        self.preloaded: list[tuple[str, int]] = []
        self.tray: list[str] = []
        self.closed_tray = 0
        self.we_started_server = False
        self.private: bool | None = True
        self.fail_preload: str | None = None
        self.keep_port_after_stop = False
        self.keep_model_after_unload = False

    def port_open(self) -> bool:
        return self.port

    def start_server(self) -> None:
        self.started += 1
        self.port = True
        self.we_started_server = True

    def wait_until_up(self, timeout: float, cancel: threading.Event) -> bool:
        return self.port and not cancel.is_set()

    def endpoint_is_private(self):
        return self.private

    def preload(self, model: str, num_ctx: int) -> None:
        if self.fail_preload:
            raise OllamaError(self.fail_preload)
        self.preloaded.append((model, num_ctx))
        self.models = [LoadedModel(model, 1000, 1000)]

    def running_models(self) -> list[LoadedModel]:
        return list(self.models)

    def unload_all(self) -> list[str]:
        names = [model.name for model in self.models]
        if not self.keep_model_after_unload:
            self.models = []
        return names

    def stop_server(self) -> None:
        self.stopped += 1
        self.we_started_server = False
        if not self.keep_port_after_stop:
            self.port = False
            self.models = []

    def tray_names(self) -> list[str]:
        return list(self.tray)

    def close_tray(self) -> list[str]:
        self.closed_tray += 1
        names = list(self.tray)
        self.tray = []
        return names


class FakeProbe:
    def __init__(self, gpu: GpuInfo | None) -> None:
        self.gpu = gpu
        self.error = None if gpu is not None else "nvidia-smi was not found."

    def read_gpu(self):
        return self.gpu, self.error


def make(gpu: GpuInfo | None = None):
    ollama = FakeOllama()
    audio = AudioGate()
    hotkeys = HotkeyBook()
    probe = FakeProbe(gpu if gpu is not None else GpuInfo(480, 12282, 0))
    service = PowerService(ollama, probe, audio, hotkeys)
    return service, ollama, audio, hotkeys, probe


def progress(_text: str) -> None:
    return None


def test_app_logic_starts_off():
    service, *_rest = make()
    assert service.state == OFF


def test_turn_on_starts_server_and_loads_the_chosen_context():
    service, ollama, audio, hotkeys, _probe = make()
    result = service.turn_on(
        model="qwen3.5:9b",
        num_ctx=8192,
        cancel=threading.Event(),
        game_name=None,
        progress=progress,
    )
    assert result.ok
    assert result.state == ON
    assert ollama.started == 1
    assert ollama.preloaded == [("qwen3.5:9b", 8192)]
    assert audio.armed is True
    assert hotkeys.assistant_enabled is True
    assert "8192" in result.message or "8,192" in result.message


def test_turn_on_uses_a_server_that_is_already_running():
    service, ollama, *_rest = make()
    ollama.port = True
    result = service.turn_on(
        model="qwen3.5:9b",
        num_ctx=4096,
        cancel=threading.Event(),
        game_name=None,
        progress=progress,
    )
    assert result.state == ON
    assert ollama.started == 0
    assert "already running" in result.message


def test_missing_model_stops_a_server_we_started():
    service, ollama, *_rest = make()
    ollama.fail_preload = "The model qwen3.5:9b is not downloaded."
    result = service.turn_on(
        model="qwen3.5:9b",
        num_ctx=8192,
        cancel=threading.Event(),
        game_name=None,
        progress=progress,
    )
    assert result.state == ERROR
    assert ollama.stopped == 1
    assert "not downloaded" in result.message


def test_public_ollama_is_refused():
    service, ollama, *_rest = make()
    ollama.port = True
    ollama.private = False
    result = service.turn_on(
        model="qwen3.5:9b",
        num_ctx=8192,
        cancel=threading.Event(),
        game_name=None,
        progress=progress,
    )
    assert result.state == ERROR
    assert "whole network" in result.message
    assert ollama.preloaded == []


def test_a_running_game_skips_the_model_and_does_not_stop_ollama():
    service, ollama, audio, hotkeys, _probe = make()
    result = service.turn_on(
        model="qwen3.5:9b",
        num_ctx=8192,
        cancel=threading.Event(),
        game_name="bg3.exe",
        progress=progress,
    )
    assert result.state == GAME
    assert ollama.preloaded == []
    assert ollama.stopped == 0
    assert audio.armed is True
    assert hotkeys.assistant_enabled is True
    assert "bg3.exe" in result.message


def test_turn_off_unloads_stops_and_confirms_the_port():
    service, ollama, audio, hotkeys, _probe = make()
    service.turn_on(
        model="qwen3.5:9b",
        num_ctx=8192,
        cancel=threading.Event(),
        game_name=None,
        progress=progress,
    )
    result = service.turn_off(emergency=False, tray_choice="ask", progress=progress)
    assert result.ok
    assert result.state == OFF
    assert ollama.stopped == 1
    assert ollama.models == []
    assert audio.listening is False
    assert audio.armed is False
    assert hotkeys.assistant_enabled is False
    assert "11434" in result.message


def test_turn_off_is_an_error_if_the_port_stays_open():
    service, ollama, *_rest = make()
    ollama.port = True
    ollama.keep_port_after_stop = True
    result = service.turn_off(emergency=False, tray_choice="leave", progress=progress)
    assert result.state == ERROR
    assert "11434" in result.message


def test_turn_off_is_an_error_if_ollama_still_holds_video_memory():
    service, ollama, *_rest = make(GpuInfo(7000, 12282, 6100))
    ollama.port = True
    ollama.models = [LoadedModel("qwen3.5:9b", 1000, 1000)]
    result = service.turn_off(emergency=False, tray_choice="leave", progress=progress)
    assert result.state == ERROR
    assert "video memory" in result.message.lower()


def test_tray_app_is_a_question_until_you_answer():
    service, ollama, *_rest = make()
    ollama.port = True
    ollama.tray = ["ollama app.exe"]
    asked = service.turn_off(emergency=False, tray_choice="ask", progress=progress)
    assert asked.needs_tray_close
    assert ollama.stopped == 0
    assert ollama.closed_tray == 0
    finished = service.turn_off(emergency=False, tray_choice="close", progress=progress)
    assert finished.state == OFF
    assert ollama.closed_tray == 1
    assert ollama.stopped == 1


def test_emergency_stop_closes_the_tray_without_asking():
    service, ollama, audio, hotkeys, _probe = make()
    ollama.port = True
    ollama.models = [LoadedModel("qwen3.5:9b", 1000, 1000)]
    ollama.tray = ["ollama app.exe"]
    hotkeys.set_assistant_enabled(True)
    audio.arm()
    result = service.turn_off(emergency=True, tray_choice="ask", progress=progress)
    assert result.state == OFF
    assert ollama.closed_tray == 1
    assert "Emergency stop" in result.message
    assert hotkeys.assistant_enabled is False
    assert audio.armed is False


def test_game_mode_unloads_but_leaves_the_server_up():
    service, ollama, audio, _hotkeys, _probe = make()
    service.turn_on(
        model="qwen3.5:9b",
        num_ctx=16384,
        cancel=threading.Event(),
        game_name=None,
        progress=progress,
    )
    result = service.enter_game_mode(progress)
    assert result.state == GAME
    assert ollama.models == []
    assert ollama.stopped == 0
    assert ollama.port is True
    assert audio.armed is True


def test_game_mode_reports_a_model_that_will_not_unload():
    service, ollama, *_rest = make()
    ollama.port = True
    ollama.models = [LoadedModel("qwen3.5:9b", 10, 10)]
    ollama.keep_model_after_unload = True
    result = service.enter_game_mode(progress)
    assert result.state == ERROR
    assert "could not unload" in result.message.lower()


def test_cancel_while_starting_does_not_claim_success():
    service, ollama, *_rest = make()
    cancel = threading.Event()
    cancel.set()
    result = service.turn_on(
        model="qwen3.5:9b",
        num_ctx=8192,
        cancel=cancel,
        game_name=None,
        progress=progress,
    )
    assert not result.ok
    assert ollama.preloaded == []
