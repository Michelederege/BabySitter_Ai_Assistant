"""Talks to Ollama on this computer only.

The server is started with no console window. Models are loaded and unloaded
through http://127.0.0.1:11434. This module never uses a shell.
"""

from __future__ import annotations

import json
import re
import os
import shutil
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import psutil

from babysitter.logsetup import get_logger
from babysitter.paths import ollama_log_path
from babysitter.platform import popen_hidden, run_hidden
from babysitter.security import (
    LOCAL_HOST,
    OLLAMA_PORT,
    bind_is_private,
    bind_is_public,
    require_local_host,
)


log = get_logger()

# A loaded model is dropped after five quiet minutes. Quit and closing the
# window unload it immediately. -1 would leave it in memory after BabySitter is gone.
IDLE_KEEP_ALIVE = "5m"


class OllamaError(Exception):
    """Something went wrong talking to Ollama. The message is safe to show."""


@dataclass
class LoadedModel:
    name: str
    size_bytes: int
    vram_bytes: int
    context_length: int = 0

    @property
    def gpu_label(self) -> str:
        return gpu_placement_label(self.size_bytes, self.vram_bytes)


def spill_problem(model: LoadedModel) -> str | None:
    """Ollama's own size split. More than 0.5 GB outside video memory is a spill."""
    if model.size_bytes <= 0:
        return None
    outside = model.size_bytes - model.vram_bytes
    if outside > 512 * 1024 * 1024:
        return (
            "Needs you: the model spilled out of video memory and will be slow. "
            "In NVIDIA Control Panel, set CUDA Sysmem Fallback Policy to "
            "Prefer No Sysmem Fallback for ollama.exe, then quit Ollama from its tray and start it again."
        )
    return None


def context_problem(model: LoadedModel, wanted_ctx: int) -> str | None:
    """None when the loaded context is unknown or already large enough."""
    if model.context_length <= 0 or model.context_length >= int(wanted_ctx):
        return None
    return (
        f"Needs you: Ollama loaded {model.context_length:,} of context, not {wanted_ctx:,}. "
        "Quit Ollama from its tray icon and start it again so the context setting applies."
    )


def gpu_placement_label(size_bytes: int, vram_bytes: int) -> str:
    if size_bytes <= 0:
        return "size unknown"
    ratio = vram_bytes / size_bytes
    if ratio >= 0.98:
        return "100% on the GPU"
    if vram_bytes <= 0:
        return "in system memory, not on the GPU"
    return f"{round(ratio * 100)}% on the GPU"


def parse_ollama_version(text: str) -> tuple[int, int, int] | None:
    """Pull the first x.y.z number out of `ollama --version` text."""
    import re

    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def version_is_older(
    found: tuple[int, int, int] | None,
    minimum: tuple[int, int, int],
) -> bool:
    if found is None:
        return False
    return found < minimum


def classify_ollama_process(name: str) -> str | None:
    """'server', 'tray', or None. Matching is by program name only."""
    lowered = (name or "").strip().lower()
    if lowered == "ollama app.exe":
        return "tray"
    if lowered in {"ollama.exe", "ollama"}:
        return "server"
    return None


def ollama_candidates(env: dict[str, str], home: Path) -> list[Path]:
    """Common install locations when `ollama` is not on PATH."""
    local = env.get("LOCALAPPDATA")
    program_files = env.get("ProgramFiles")
    program_files_x86 = env.get("ProgramFiles(x86)")
    candidates: list[Path] = []
    if local:
        candidates.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
    if program_files:
        candidates.append(Path(program_files) / "Ollama" / "ollama.exe")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Ollama" / "ollama.exe")
    candidates.append(home / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe")
    return candidates


def find_ollama_executable() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    if sys.platform != "win32":
        return None
    for candidate in ollama_candidates(dict(os.environ), Path.home()):
        if candidate.is_file():
            return str(candidate)
    return None


def parse_listen_addresses(connections, port: int = OLLAMA_PORT) -> list[str] | None:
    """Read listen addresses from psutil connection rows. None if unreadable."""
    if connections is None:
        return None
    addresses: list[str] = []
    for row in connections:
        local = getattr(row, "laddr", None)
        status = getattr(row, "status", "")
        if not local:
            continue
        if getattr(local, "port", None) != port:
            continue
        if status and status != psutil.CONN_LISTEN:
            continue
        addresses.append(getattr(local, "ip", ""))
    return addresses


class OllamaClient:
    def __init__(self, host: str = LOCAL_HOST, port: int = OLLAMA_PORT) -> None:
        require_local_host(host)
        self.host = host
        self.port = port
        self._proc: subprocess.Popen | None = None
        self._log_handle = None
        self._lock = threading.Lock()
        self.we_started_server = False
        self.last_turn_stats: dict[str, int] = {}

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def port_open(self, timeout: float = 0.1) -> bool:
        """Is something listening on Ollama's port on this PC?

        On Windows a refused connection to 127.0.0.1 is retried until the
        timeout, so a closed port always cost the full wait: 0.4 s, every 2
        seconds in the status check and on the window's thread when it closed
        or hid. An open loopback port answers in milliseconds, so 0.1 s is
        plenty (measured 27 Nov: open 15 ms, closed = the timeout).
        """
        try:
            with socket.create_connection((self.host, self.port), timeout=timeout):
                return True
        except OSError:
            return False

    def listen_addresses(self) -> list[str] | None:
        try:
            connections = psutil.net_connections(kind="inet")
        except (psutil.Error, OSError, PermissionError):
            return None
        return parse_listen_addresses(connections, self.port)

    def endpoint_is_private(self) -> bool | None:
        """True, False, or None when this computer would not say."""
        addresses = self.listen_addresses()
        if addresses is None:
            return None
        if not addresses:
            return None
        if bind_is_public(addresses):
            return False
        if bind_is_private(addresses):
            return True
        return False

    def read_version_text(self) -> tuple[str, str | None]:
        """Run `ollama --version`. Returns (output, error message)."""
        executable = find_ollama_executable()
        if not executable:
            return "", "Ollama is not installed, or it is not on the PATH."
        try:
            completed = run_hidden([executable, "--version"], timeout=8)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "", f"Could not run ollama --version ({exc})."
        text = (completed.stdout or "") + (completed.stderr or "")
        return text.strip(), None

    def _open(self, method: str, path: str, body: dict | None, timeout: float):
        if not path.startswith("/"):
            raise OllamaError("Bad Ollama path.")
        url = self.base_url + path
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        model = "" if not body else str(body.get("model", ""))
        log.info("%s %s model=%s", method, path, model)
        return urllib.request.urlopen(request, timeout=timeout)

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float = 30):
        model = "" if not body else str(body.get("model", ""))
        try:
            with self._open(method, path, body, timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise OllamaError(_friendly_http(exc.code, detail, model)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OllamaError(_friendly_network(exc)) from None
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise OllamaError("Ollama answered with something that was not JSON.") from exc

    def ask(self, model: str, prompt: str, num_ctx: int) -> str:
        """One local reply. The prompt and the reply are not written to the log."""
        parts = list(self.iter_reply(model, prompt, num_ctx))
        reply = "".join(parts).strip()
        if not reply:
            raise OllamaError("The model returned an empty reply.")
        return reply

    def iter_reply(
        self,
        model: str,
        prompt: str,
        num_ctx: int,
        cancel=None,
        history=None,
        images=None,
        keep_alive=IDLE_KEEP_ALIVE,
        num_batch=None,
        facts=None,
        personality: str = "",
        context_note: str = "",
    ):
        """Yield each new piece as Ollama writes it. Nothing is logged."""
        body = chat_body(
            model,
            prompt,
            num_ctx,
            history,
            keep_alive=keep_alive,
            num_batch=num_batch,
            facts=facts,
            personality=personality,
            context_note=context_note,
        )
        if images:
            body["messages"][-1]["images"] = list(images)
        self.last_turn_stats = {}
        # The watcher closes the stream on a cancel. It also has to stop
        # when the reply ends without one, or every turn leaves a thread
        # behind that holds the old connection open.
        finished = threading.Event()
        try:
            with self._open("POST", "/api/chat", body, timeout=180) as response:
                if cancel is not None:
                    threading.Thread(
                        target=_close_when_cancelled,
                        args=(cancel, response, finished),
                        daemon=True,
                    ).start()
                while True:
                    if cancel is not None and cancel.is_set():
                        break
                    raw = response.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", "replace")
                    stats = stats_from_stream_line(line)
                    if stats:
                        self.last_turn_stats = stats
                    piece, done = content_from_stream_line(line)
                    if piece:
                        yield piece
                    if done:
                        break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise OllamaError(_friendly_http(exc.code, detail, model)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if cancel is not None and cancel.is_set():
                return
            raise OllamaError(_friendly_network(exc)) from None
        except ValueError:
            # A read on a stream the watcher just closed.
            if cancel is not None and cancel.is_set():
                return
            raise
        finally:
            finished.set()

    def installed_models(self) -> list[str]:
        payload = self._request("GET", "/api/tags", timeout=8)
        names: list[str] = []
        for item in payload.get("models") or []:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.append(item["name"])
        return names

    def running_models(self) -> list[LoadedModel]:
        payload = self._request("GET", "/api/ps", timeout=5)
        return models_from_ps(payload)

    def delete_model(self, name: str) -> None:
        cleaned = (name or "").strip()
        if not cleaned:
            raise OllamaError("Type or choose a model name first.")
        self._request("DELETE", "/api/delete", {"model": cleaned}, timeout=30)

    def preload(self, model: str, num_ctx: int, num_batch: int | None = None) -> None:
        """Load a model and leave it in memory.

        An empty message list makes Ollama load the model and answer at
        once, without generating a single token. That is a second or two
        faster than asking for a word and throwing it away.
        """
        options = {"num_ctx": int(num_ctx)}
        if num_batch:
            options["num_batch"] = int(num_batch)
        body = {
            "model": model,
            "messages": [],
            "stream": False,
            "keep_alive": IDLE_KEEP_ALIVE,
            "options": options,
        }
        self._request("POST", "/api/chat", body, timeout=240)

    def unload_all(self) -> list[str]:
        unloaded: list[str] = []
        for model in self.running_models():
            self._unload_one(model.name)
            unloaded.append(model.name)
        return unloaded

    def _unload_one(self, name: str) -> None:
        # Ollama treats keep_alive 0 as "drop this model from memory".
        try:
            self._request(
                "POST",
                "/api/generate",
                {"model": name, "keep_alive": 0},
                timeout=60,
            )
        except OllamaError:
            self._request(
                "POST",
                "/api/generate",
                {"model": name, "keep_alive": 0, "prompt": " "},
                timeout=60,
            )

    def start_server(self, num_ctx: int = 4096) -> None:
        if self.port_open():
            return
        executable = find_ollama_executable()
        if not executable:
            raise OllamaError(
                "Ollama is not installed, or BabySitter cannot find ollama.exe. "
                "Install it from https://ollama.com/download and open BabySitter again."
            )
        environment = server_environment(os.environ, LOCAL_HOST, self.port, num_ctx)
        log_path = ollama_log_path()
        handle = open(log_path, "ab")
        try:
            proc = popen_hidden(
                [executable, "serve"],
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=handle,
                env=environment,
            )
        except OSError as exc:
            handle.close()
            raise OllamaError(f"Could not start Ollama ({exc}).") from exc
        from babysitter.platform import end_with_this_app

        end_with_this_app(proc)  # a crash or Task Manager never leaves it running
        with self._lock:
            self._proc = proc
            self._log_handle = handle
            self.we_started_server = True
        log.info("Started Ollama hidden (pid %s).", proc.pid)

    def wait_until_up(self, timeout: float, cancel: threading.Event, progress=None) -> bool:
        deadline = timeout
        waited = 0.0
        told_upgrade = False
        while waited < deadline:
            if cancel.is_set():
                return False
            if self.port_open():
                return True
            if self._child_exited():
                tail = _tail(ollama_log_path())
                raise OllamaError(
                    "Ollama quit as soon as it started. "
                    + (f"It said: {tail}" if tail else "The log was empty.")
                )
            if progress is not None and waited >= 12 and not told_upgrade:
                told_upgrade = True
                progress(
                    "Working: Ollama is upgrading its model storage. "
                    "The first launch after an update can sit for a few minutes."
                )
            cancel.wait(0.4)
            waited += 0.4
        return self.port_open()

    def _child_exited(self) -> bool:
        with self._lock:
            proc = self._proc
        return bool(proc) and proc.poll() is not None and not self.port_open()

    def stop_server(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is not None and proc.poll() is None:
            _terminate_popen(proc)
        for process in _processes_of_kind("server"):
            _terminate_psutil(process)
        self.we_started_server = False
        handle = None
        with self._lock:
            handle = self._log_handle
            self._log_handle = None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def abort(self) -> None:
        """Stop the server immediately. Used by the emergency key."""
        self.stop_server()

    def tray_names(self) -> list[str]:
        return [process.name() for process in _processes_of_kind("tray")]

    def close_tray(self) -> list[str]:
        closed: list[str] = []
        for process in _processes_of_kind("tray"):
            name = process.name()
            _terminate_psutil(process)
            closed.append(name)
        return closed


def _close_when_cancelled(cancel, response, finished=None) -> None:
    while not cancel.wait(0.25):
        if finished is not None and finished.is_set():
            return
    if finished is not None and finished.is_set():
        return
    try:
        response.close()
    except Exception:
        return


def server_environment(base, host: str, port: int, num_ctx: int = 4096) -> dict:
    """Settings for the Ollama BabySitter starts. They do not change one that is already running."""
    environment = dict(base)
    environment["OLLAMA_HOST"] = f"{host}:{port}"
    # The level that is turning on sets the default. A later request can still
    # send its own num_ctx. 16,384 here made a quiet load reserve a long cache.
    environment["OLLAMA_CONTEXT_LENGTH"] = str(max(2048, min(16384, int(num_ctx))))
    # Quantized KV cache needs flash attention. q4_0 is about half of q8_0.
    environment["OLLAMA_FLASH_ATTENTION"] = "1"
    environment["OLLAMA_KV_CACHE_TYPE"] = "q4_0"
    environment["OLLAMA_NUM_PARALLEL"] = "1"
    environment["OLLAMA_MAX_LOADED_MODELS"] = "1"
    environment["OLLAMA_KEEP_ALIVE"] = "5m"
    # A signed-in Ollama also serves its cloud models through this same
    # local port. BabySitter promises that a reply never leaves this PC,
    # so cloud models are off for the Ollama that BabySitter starts.
    environment["OLLAMA_NO_CLOUD"] = "1"
    return environment


# The three examples are chosen to be unlikely questions: a 9B model copied an
# earlier octopus example word for word when asked for "something interesting".
# Digits, not words, for numbers: asked to spell numbers out, it wrote "thirty
# thousand miles" to the moon and "two hundred and zero-six" bones (tested on
# 27 Nov). The voice reads digits properly by itself.
# Written for the ear. Every word of the reply is spoken by a voice, so the
# rules are the ones voice-agent guides agree on (Deepgram, LiveKit, Vapi,
# Layercode): say that it is spoken, keep turns short, say numbers and symbols
# as words, no markup. The name is filled in from the nickname you gave it.
# This text stays the same for a whole session so Ollama's prompt cache holds.
VOICE_SYSTEM = (
    "You are {name}, a warm, quick-witted voice companion living on this one PC. "
    "Everything you write is spoken aloud by a voice, so write the way a person talks, not the way a page reads. "
    "Personality: natural, curious, and easy to talk to, like a sharp friend sitting nearby. "
    "Dry warmth and light humor are welcome, never at the user's expense; drop them after a mistake or bad news. "
    "Have real opinions and give them when asked. Disagree plainly and kindly when the user is wrong. "
    "Do not flatter, and do not praise a question. "
    "Never open with stiff filler like 'Certainly!', 'Of course!', 'Great question!', 'Absolutely!', or 'As an AI'. "
    "Speech: answer in one to three short sentences, the answer first. "
    "Use contractions, everyday words, and the rhythm of speech; a 'so', 'well', or 'honestly' is fine now and then. "
    "Vary your words and openings from turn to turn. Pick the precise, vivid word over the generic one, "
    "and match the user's tone: playful with playful, calm and careful with worry or stress. "
    "When feelings come up, acknowledge them in a few words before helping. "
    "Write numbers as digits, like 384,000 or 206; the voice reads them correctly. "
    "No lists, headings, bold, emoji, tables, or parentheses in the spoken part. "
    "Put code, long lists, or detail after those sentences, and only when asked for. "
    "Conversation: answer what was just asked. Bring up something from earlier only when it "
    "directly matters to this question, never as a habit. "
    "Most replies end without a question. Ask one short question back only when you need the answer to help. "
    "If you did not understand, say so briefly and ask. "
    "Do not repeat the whole answer, and do not ask them to confirm a chat. "
    "A yes or a no is for one change to this PC, or for something that leaves it. "
    "Rules: use the conversation so far, including local tool, file, reminder, or scan turns. "
    "Do not invent a memory you were not given, or a fact you are unsure of; say you are not sure instead. "
    "Do not paste shell commands, PowerShell, or Task Manager steps. "
    "A scan of this PC is performed before you are asked. Do not invent a scan result. "
    "Reminders, timers, the journal, and file search are saved on this PC before you are asked. "
    "When a clock note is given, it is background. Mention the time or date only when the question is about it, "
    "and do not explain time zones. "
    "How it sounds, by example. "
    "User: Should I paint the hallway grey or green? You: Green, if it gets any daylight; grey can feel like a "
    "waiting room. A soft sage is hard to get wrong. "
    "User: My code keeps crashing and I'm fed up. You: That's maddening, especially when you can't see why. "
    "Paste the last error and we'll find it. "
    "User: Is a tomato a fruit? You: Botanically, yes, it's a berry. In the kitchen it's a vegetable, so you're "
    "right either way."
)
STABLE_SYSTEM = VOICE_SYSTEM.format(name="BabySitter")


_TIME_WORDS = re.compile(
    r"\b(time|date|day|days|today|tonight|tomorrow|yesterday|morning|afternoon|evening|night|week|weekend|"
    r"month|year|hour|hours|minute|minutes|now|late|early|soon|when|schedule|calendar|remind|reminder|deadline|"
    r"due|o'?clock|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|"
    r"june|july|august|september|october|november|december|birthday|holiday|christmas|sleep|bed|bedtime|wake|"
    r"breakfast|lunch|dinner|season|age|old|ago|until|left|countdown|plan|plans|exam|class|meeting)\b",
    re.IGNORECASE,
)


def clock_matters(prompt: str) -> bool:
    """True when the question is about time, days, or plans, so the clock helps."""
    return bool(_TIME_WORDS.search(prompt or ""))


def sampling_for(model: str) -> dict:
    """Each model family's own recommended sampling for chat.

    Qwen 3.x non-thinking: temperature 0.7, top_p 0.8, top_k 20, presence 1.5
    (the model card). Gemma: Google's defaults, temperature 1.0, top_p 0.95,
    top_k 64. Gemma was getting Qwen's numbers, which make it flatter and
    more repetitive than it is meant to be.
    """
    name = (model or "").lower()
    if name.startswith("gemma"):
        return {"temperature": 1.0, "top_p": 0.95, "top_k": 64}
    return {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.5}


def chat_body(
    model: str,
    prompt: str,
    num_ctx: int,
    history=None,
    keep_alive=IDLE_KEEP_ALIVE,
    num_batch=None,
    facts=None,
    personality: str = "",
    context_note: str = "",
) -> dict:
    """The local chat request. Voice turns do not use hidden thinking.

    num_ctx and num_batch stay the same for every request at one level.
    Changing either one makes Ollama drop the loaded model and read it again.
    """
    options = {
        "num_ctx": int(num_ctx),
        **sampling_for(model),
        # A voice turn that runs for thousands of tokens is the long pause.
        # 512 is enough for the short spoken part and the rest on the screen.
        "num_predict": 512,
    }
    if num_batch:
        options["num_batch"] = int(num_batch)
    return {
        "model": model,
        "messages": chat_messages(
            prompt,
            history,
            facts=facts,
            personality=personality,
            context_note=context_note,
        ),
        "stream": True,
        "keep_alive": keep_alive,
        "think": False,
        "options": options,
    }


def content_from_stream_line(line: str) -> tuple[str, bool]:
    """One streamed line: the new words, and whether the reply is finished."""
    text = (line or "").strip()
    if not text:
        return "", False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OllamaError("Ollama answered with something that was not JSON.") from exc
    if not isinstance(payload, dict):
        return "", False
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        raise OllamaError(error.strip())
    message = payload.get("message")
    piece = ""
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        piece = message["content"]
    return piece, bool(payload.get("done"))


def stats_from_stream_line(line: str) -> dict[str, int]:
    """Counts and speeds from a finished Ollama line. No words."""
    text = (line or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict) or not payload.get("done"):
        return {}
    stats: dict[str, int] = {}
    for source, dest in (
        ("prompt_eval_count", "prompt_tokens"),
        ("eval_count", "gen_tokens"),
    ):
        value = payload.get(source)
        if isinstance(value, int) and not isinstance(value, bool):
            stats[dest] = value
    prompt_ns = payload.get("prompt_eval_duration")
    gen_ns = payload.get("eval_duration")
    load_ns = payload.get("load_duration")
    if isinstance(load_ns, int) and not isinstance(load_ns, bool):
        stats["load_ms"] = int(load_ns / 1_000_000)
    if isinstance(prompt_ns, int) and not isinstance(prompt_ns, bool) and prompt_ns > 0:
        stats["prompt_ms"] = max(1, int(prompt_ns / 1_000_000))
        tokens = stats.get("prompt_tokens", 0)
        if tokens:
            stats["prompt_tps"] = int(tokens / (prompt_ns / 1_000_000_000))
    if isinstance(gen_ns, int) and not isinstance(gen_ns, bool) and gen_ns > 0:
        stats["gen_ms"] = max(1, int(gen_ns / 1_000_000))
        tokens = stats.get("gen_tokens", 0)
        if tokens:
            stats["gen_tps"] = int(tokens / (gen_ns / 1_000_000_000))
    return stats


def system_prompt(personality: str = "", name: str = "") -> str:
    """The standing instructions, under the nickname when there is one.

    With a nickname, the persona sentence ("Your name is Kari...") used to sit
    after "You are BabySitter", and the two names fought. Now the name is in
    the first line, and the persona sentence only adds its manner.
    """
    if not name:
        try:
            from babysitter.personality import persona_name

            name = persona_name()
        except Exception:  # noqa: BLE001
            name = ""
    base = VOICE_SYSTEM.format(name=name or "BabySitter")
    extra = (personality or "").strip()
    if not extra:
        return base
    return f"{base} {extra}"


def chat_messages(
    prompt: str,
    history=None,
    now=None,
    facts=None,
    personality: str = "",
    context_note: str = "",
) -> list[dict]:
    """The standing instructions stay fixed. The clock is only on the newest line."""
    from datetime import datetime

    moment = now or datetime.now().astimezone()
    clock = moment.strftime("%A, %B %d, %Y, %I:%M %p")
    zone = moment.tzname() or "local time"
    messages = [{"role": "system", "content": system_prompt(personality)}]
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})
    # The question first. The clock only goes with questions about time, days,
    # or plans: with it on every line, the model kept working the hour into
    # unrelated answers ("Midnight, which fits that 2:36 AM hour").
    line = prompt
    if clock_matters(prompt):
        line += f"\n\n(Background, not part of the question. Clock on this PC: {clock}, {zone}.)"
    saved = [str(fact).strip() for fact in facts or [] if str(fact).strip()]
    if saved:
        line += " Saved facts from this PC: " + " | ".join(saved[:2])
    desk = (context_note or "").strip()
    if desk:
        line += f" Active desk context on this PC: {desk}"
    messages.append({"role": "user", "content": line})
    return messages


def models_from_ps(payload: dict) -> list[LoadedModel]:
    models: list[LoadedModel] = []
    for item in payload.get("models") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model") or ""
        if not name:
            continue
        context = item.get("context_length") or 0
        try:
            context = int(context)
        except (TypeError, ValueError):
            context = 0
        models.append(
            LoadedModel(
                name=str(name),
                size_bytes=int(item.get("size") or 0),
                vram_bytes=int(item.get("size_vram") or 0),
                context_length=context,
            )
        )
    return models


def _friendly_http(code: int, detail: str, model: str) -> str:
    lowered = detail.lower()
    if "out of memory" in lowered or ("memory" in lowered and "cuda" in lowered):
        return (
            "Needs you: not enough video memory. "
            "A game or another app may be using the card. Nothing was changed."
        )
    if code == 404 or "not found" in lowered:
        shown = model or "that model"
        return (
            f"The model {shown} is not downloaded. "
            "BabySitter does not download it for you in this phase. "
            f"When you are ready, open a terminal and run: ollama pull {shown}"
        )
    if detail:
        return f"Ollama returned an error ({code}): {detail}"
    return f"Ollama returned an error ({code})."


def _friendly_network(exc: Exception) -> str:
    text = str(exc)
    if "timed out" in text.lower():
        return "Ollama took too long to answer."
    return "Could not reach Ollama at 127.0.0.1:11434. It may be off."


def _processes_of_kind(kind: str) -> list[psutil.Process]:
    found: list[psutil.Process] = []
    try:
        processes = list(psutil.process_iter(["name"]))
    except (psutil.Error, OSError):
        return found
    for process in processes:
        try:
            name = process.info.get("name") or process.name()
        except (psutil.Error, OSError):
            continue
        if classify_ollama_process(name) == kind:
            found.append(process)
    return found


def _terminate_popen(proc: subprocess.Popen) -> None:
    try:
        if proc.pid:
            _terminate_psutil(psutil.Process(proc.pid))
    except (psutil.Error, OSError):
        try:
            proc.terminate()
        except OSError:
            pass
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
    except OSError:
        pass


def _terminate_psutil(process: psutil.Process) -> None:
    """Stop this process and the runners it spawned. A parent kill can leave the model loaded."""
    victims = [process]
    try:
        victims = process.children(recursive=True) + [process]
    except (psutil.Error, OSError):
        victims = [process]
    for proc in victims:
        try:
            proc.terminate()
        except (psutil.Error, OSError):
            continue
    _gone, alive = psutil.wait_procs(victims, timeout=5)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.Error, OSError):
            pass


def _tail(path: Path, limit: int = 400) -> str:
    try:
        data = path.read_bytes()[-limit:]
    except OSError:
        return ""
    return data.decode("utf-8", "replace").strip()
