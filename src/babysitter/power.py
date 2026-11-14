"""The on / off / game-mode switch.

Off unloads every model, stops Ollama, closes the microphone hook, and
turns off future assistant hotkeys. The emergency key and the turn-on key
stay active.

Game mode unloads models so a game can use the graphics card, but it leaves
the Ollama program running and leaves the voice hook armed. Phase 1 does
not open the microphone in either mode.

The app always starts off.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from babysitter.audio import AudioGate
from babysitter.hotkeys import HotkeyBook
from babysitter.intelligence import batch_for
from babysitter.ollama import OllamaClient, OllamaError, context_problem, spill_problem
from babysitter.pictures import room_for_model
from babysitter.status import StatusCollector, explain_gpu_hold, format_mib
from babysitter.vram import low_load_note


OFF = "off"
STARTING = "starting"
ON = "on"
GAME = "game"
ERROR = "error"


@dataclass
class PowerResult:
    state: str
    message: str
    ok: bool
    needs_tray_close: bool = False
    tray_names: list[str] = field(default_factory=list)


class PowerService:
    def __init__(
        self,
        ollama: OllamaClient,
        probe: StatusCollector,
        audio: AudioGate,
        hotkeys: HotkeyBook,
    ) -> None:
        self.ollama = ollama
        self.probe = probe
        self.audio = audio
        self.hotkeys = hotkeys
        self.state = OFF
        self._progress = lambda _text: None

    def turn_on(
        self,
        *,
        model: str,
        num_ctx: int,
        cancel: threading.Event,
        game_name: str | None,
        progress,
    ) -> PowerResult:
        self._progress = progress
        if self.state == ON and not cancel.is_set():
            return PowerResult(ON, "The AI is already on.", True)
        self.state = STARTING
        self._load_note = ""
        progress("Starting Ollama in the background…")
        try:
            if cancel.is_set():
                return self._cancelled()
            if not self.ollama.port_open():
                self.ollama.start_server()
                progress("Waiting for Ollama to answer on this computer…")
                up = self.ollama.wait_until_up(180, cancel, progress)
                if cancel.is_set():
                    return self._cancelled()
                if not up:
                    self._stop_if_we_started()
                    return self._fail(
                        "Ollama did not answer at 127.0.0.1:11434. "
                        "If you just installed it, restart the PC and try again."
                    )
            private = self.ollama.endpoint_is_private()
            if private is False:
                self._stop_if_we_started()
                return self._fail(
                    "Ollama is listening on the whole network, not only this computer. "
                    "Turn the AI off and let BabySitter start it, "
                    "or quit Ollama's own tray app and try again."
                )
            if cancel.is_set():
                return self._cancelled()
            if game_name:
                result = self.enter_game_mode(progress=progress)
                result.message = (
                    f"{game_name} is running, so no model was loaded. "
                    "Game mode is on and the graphics card is free."
                )
                return result
            progress(f"Loading {model}. The first time can take a minute…")
            gpu, _gpu_error = self.probe.read_gpu()
            free = None if gpu is None else gpu.total_mib - gpu.used_mib
            if room_for_model(free, model, num_ctx) and self.ollama.port_open():
                self.ollama.unload_all()
                gpu, _gpu_error = self.probe.read_gpu()
                free = None if gpu is None else gpu.total_mib - gpu.used_mib
            blocked = room_for_model(free, model, num_ctx)
            if blocked:
                self._stop_if_we_started()
                return self._fail(blocked)
            self.ollama.preload(model, num_ctx, batch_for(model, num_ctx))
            placed = self._after_load(model, num_ctx)
            if placed:
                return placed
            if cancel.is_set():
                return self._cancelled()
        except OllamaError as exc:
            if cancel.is_set():
                return self._cancelled()
            self._stop_if_we_started()
            return self._fail(str(exc))
        except OSError as exc:
            self._stop_if_we_started()
            return self._fail(f"Could not finish turning on ({exc}).")

        self.audio.arm()
        self.hotkeys.set_assistant_enabled(True)
        self.state = ON
        if self.ollama.we_started_server:
            where = "Ollama was started with no window, and only this computer can reach it."
        else:
            where = "Ollama was already running, so BabySitter used it."
        privacy = ""
        if private is None and not self.ollama.we_started_server:
            privacy = " I could not check whether other computers can reach Ollama."
        note = getattr(self, "_load_note", "")
        self._load_note = ""
        extra = f" {note}" if note else ""
        return PowerResult(
            ON,
            f"The AI is on. {model} is loaded ({num_ctx:,} of context). {where}{privacy}{extra}",
            True,
        )

    def reload_model(self, *, model: str, num_ctx: int, cancel: threading.Event, progress) -> PowerResult:
        """Apply a new Low / Medium / High setting to the model that is already on."""
        if self.state == GAME:
            return PowerResult(
                GAME,
                "The model is unloaded in game mode. The new setting applies when you wake it.",
                True,
            )
        if self.state != ON:
            return PowerResult(self.state, "Turn the AI on before reloading the model.", False)
        self._load_note = ""
        progress("Reloading the model with the new intelligence setting…")
        try:
            if cancel.is_set():
                return self._cancelled()
            if self.ollama.port_open():
                self.ollama.unload_all()
            gpu, _gpu_error = self.probe.read_gpu()
            free = None if gpu is None else gpu.total_mib - gpu.used_mib
            blocked = room_for_model(free, model, num_ctx)
            if blocked:
                return self._fail(blocked)
            self.ollama.preload(model, num_ctx, batch_for(model, num_ctx))
            placed = self._after_load(model, num_ctx)
            if placed:
                return placed
        except OllamaError as exc:
            return self._fail(str(exc))
        self.state = ON
        note = getattr(self, "_load_note", "")
        self._load_note = ""
        extra = f" {note}" if note else ""
        return PowerResult(ON, f"Reloaded {model} with {num_ctx:,} of context.{extra}", True)

    def _after_load(self, model: str, num_ctx: int) -> PowerResult | None:
        """Unload a spilled model. A short context is a warning, not a crash."""
        try:
            running = self.ollama.running_models()
        except OllamaError:
            return None
        match = next((item for item in running if model.split(":")[0] in item.name), None)
        if match is None:
            return None
        spilled = spill_problem(match)
        if spilled:
            try:
                self.ollama.unload_all()
            except OllamaError:
                pass
            self._stop_if_we_started()
            return self._fail(spilled)
        notes: list[str] = []
        short = context_problem(match, num_ctx)
        if short:
            notes.append(short)
        budget = low_load_note(match.name, match.vram_bytes, num_ctx)
        if budget:
            notes.append(budget)
        if notes:
            self._load_note = " ".join(notes)
        return None

    def enter_game_mode(self, progress) -> PowerResult:
        self._progress = progress
        progress("Unloading models so the graphics card is free…")
        try:
            if self.ollama.port_open():
                self.ollama.unload_all()
                still = self.ollama.running_models()
                if still:
                    names = ", ".join(model.name for model in still)
                    return self._fail(f"Game mode could not unload: {names}.")
        except OllamaError as exc:
            return self._fail(f"Game mode could not unload the model. {exc}")
        # Voice stays armed. The server stays up so waking the model is faster.
        self.audio.arm()
        self.hotkeys.set_assistant_enabled(True)
        self.state = GAME
        return PowerResult(
            GAME,
            "Game mode. Models are unloaded. The microphone is still closed "
            "(voice comes later), and Ollama is left running with nothing loaded.",
            True,
        )

    def turn_off(
        self,
        *,
        emergency: bool,
        tray_choice: str,
        progress,
    ) -> PowerResult:
        """tray_choice is 'ask', 'close', or 'leave'."""
        self._progress = progress
        progress("Turning the AI off…")
        self.audio.release()
        self.hotkeys.set_assistant_enabled(False)
        notes: list[str] = []
        before = self._gpu_used()
        try:
            if self.ollama.port_open():
                progress("Unloading models…")
                names = self.ollama.unload_all()
                if names:
                    notes.append("Unloaded " + ", ".join(names) + ".")
        except OllamaError as exc:
            notes.append(f"Could not unload cleanly ({exc}). Stopping Ollama anyway.")

        tray = self.ollama.tray_names()
        choice = "close" if emergency else tray_choice
        if tray and choice == "ask":
            # Models are already unloaded. Ask before killing the tray app,
            # because that app is not part of BabySitter.
            self.state = ERROR
            return PowerResult(
                state=ERROR,
                message=(
                    "Models were unloaded, but Ollama's own tray app is still running. "
                    "It can load a model again and hold the graphics card. Close it?"
                ),
                ok=False,
                needs_tray_close=True,
                tray_names=tray,
            )

        if tray and choice == "close":
            progress("Closing Ollama's tray app…")
            closed = self.ollama.close_tray()
            if closed:
                if emergency:
                    notes.append(
                        "Emergency stop also closed Ollama's tray app "
                        "so it could not reload a model."
                    )
                else:
                    notes.append("Closed Ollama's tray app.")

        progress("Stopping Ollama…")
        self.ollama.stop_server()
        return self._confirm_off(before, notes)

    def _confirm_off(self, before_mib: int | None, notes: list[str]) -> PowerResult:
        if self.ollama.port_open():
            return self._fail(
                "The AI is not fully off. Something is still listening on port 11434. "
                + " ".join(notes)
            )
        gpu, gpu_error = self.probe.read_gpu()
        held: bool | None
        detail: str
        if gpu is None:
            held, detail = None, gpu_error or "Video memory could not be checked."
        else:
            held, detail = explain_gpu_hold(gpu.ollama_mib)
            detail = (
                f"{detail} Video memory in use is {format_mib(gpu.used_mib)} "
                f"of {format_mib(gpu.total_mib)}."
            )
            if before_mib is not None:
                detail += f" Before the shutdown it was {format_mib(before_mib)}."
        if held is True:
            return self._fail(detail + " " + " ".join(notes))
        self.state = OFF
        message = "The AI is off. Nothing is listening on port 11434. " + detail
        if notes:
            message += " " + " ".join(notes)
        if held is None:
            message += " Look at the video memory card to be sure the model is gone."
        return PowerResult(OFF, message.strip(), True)

    def _gpu_used(self) -> int | None:
        gpu, _error = self.probe.read_gpu()
        if gpu is None:
            return None
        return gpu.used_mib

    def _stop_if_we_started(self) -> None:
        if self.ollama.we_started_server:
            self.ollama.stop_server()

    def _fail(self, message: str) -> PowerResult:
        self.state = ERROR
        self.audio.release()
        self.hotkeys.set_assistant_enabled(False)
        return PowerResult(ERROR, message.strip(), False)

    def _cancelled(self) -> PowerResult:
        return PowerResult(self.state, "Stopped while starting.", False)
