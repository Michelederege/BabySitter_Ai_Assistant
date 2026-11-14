"""Talks to Ollama on this computer only.

The server is started with no console window. Models are loaded and unloaded
through http://127.0.0.1:11434. This module never uses a shell.
"""

from __future__ import annotations

import json
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


class OllamaError(Exception):
    """Something went wrong talking to Ollama. The message is safe to show."""


@dataclass
class LoadedModel:
    name: str
    size_bytes: int
    vram_bytes: int

    @property
    def gpu_label(self) -> str:
        return gpu_placement_label(self.size_bytes, self.vram_bytes)


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

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def port_open(self, timeout: float = 0.4) -> bool:
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

    def iter_reply(self, model: str, prompt: str, num_ctx: int):
        """Yield each new piece as Ollama writes it. Nothing is logged."""
        body = chat_body(model, prompt, num_ctx)
        try:
            with self._open("POST", "/api/chat", body, timeout=180) as response:
                while True:
                    raw = response.readline()
                    if not raw:
                        break
                    piece, done = content_from_stream_line(raw.decode("utf-8", "replace"))
                    if piece:
                        yield piece
                    if done:
                        break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise OllamaError(_friendly_http(exc.code, detail, model)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OllamaError(_friendly_network(exc)) from None

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

    def preload(self, model: str, num_ctx: int) -> None:
        """Load a model and leave it in memory. The one-word reply is discarded."""
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with only the word ready."}],
            "stream": False,
            "keep_alive": -1,
            "options": {"num_ctx": int(num_ctx), "num_predict": 8, "temperature": 0},
        }
        if "qwen" in model.lower():
            body["think"] = False
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

    def start_server(self) -> None:
        if self.port_open():
            return
        executable = find_ollama_executable()
        if not executable:
            raise OllamaError(
                "Ollama is not installed, or BabySitter cannot find ollama.exe. "
                "Install it from https://ollama.com/download and open BabySitter again."
            )
        environment = os.environ.copy()
        # Force a private listener even if the user previously set OLLAMA_HOST
        # to 0.0.0.0. This applies only to the server BabySitter starts.
        environment["OLLAMA_HOST"] = f"{LOCAL_HOST}:{self.port}"
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
        with self._lock:
            self._proc = proc
            self._log_handle = handle
            self.we_started_server = True
        log.info("Started Ollama hidden (pid %s).", proc.pid)

    def wait_until_up(self, timeout: float, cancel: threading.Event) -> bool:
        deadline = timeout
        waited = 0.0
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


def chat_body(model: str, prompt: str, num_ctx: int) -> dict:
    """The local chat request. Qwen skips its hidden thinking so the first words arrive sooner."""
    body = {
        "model": model,
        "messages": chat_messages(prompt),
        "stream": True,
        "keep_alive": -1,
        "options": {"num_ctx": int(num_ctx)},
    }
    if "qwen" in model.lower():
        body["think"] = False
    return body


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


def chat_messages(prompt: str, now=None) -> list[dict]:
    """Tell the local model the clock. The model has no clock of its own."""
    from datetime import datetime

    moment = now or datetime.now().astimezone()
    clock = moment.strftime("%A, %B %d, %Y, %I:%M %p")
    zone = moment.tzname() or "local time"
    return [
        {
            "role": "system",
            "content": (
                f"Current local time: {clock} ({zone}). "
                "Use this when asked the time or the date. "
                "Start with one sentence of no more than 12 words. "
                "Put any extra detail after that sentence."
            ),
        },
        {"role": "user", "content": prompt},
    ]


def models_from_ps(payload: dict) -> list[LoadedModel]:
    models: list[LoadedModel] = []
    for item in payload.get("models") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model") or ""
        if not name:
            continue
        models.append(
            LoadedModel(
                name=str(name),
                size_bytes=int(item.get("size") or 0),
                vram_bytes=int(item.get("size_vram") or 0),
            )
        )
    return models


def _friendly_http(code: int, detail: str, model: str) -> str:
    lowered = detail.lower()
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
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
    except OSError:
        pass


def _terminate_psutil(process: psutil.Process) -> None:
    try:
        process.terminate()
        process.wait(timeout=5)
    except psutil.TimeoutExpired:
        try:
            process.kill()
        except psutil.Error:
            pass
    except psutil.Error:
        pass


def _tail(path: Path, limit: int = 400) -> str:
    try:
        data = path.read_bytes()[-limit:]
    except OSError:
        return ""
    return data.decode("utf-8", "replace").strip()
