"""Reads GPU, CPU, memory, and which models are loaded.

The numbers are refreshed every 2 seconds by the window. Reading them
does not change anything on the computer.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from dataclasses import dataclass, field

import psutil

from babysitter.ollama import LoadedModel, OllamaError, models_from_ps
from babysitter.platform import run_hidden


@dataclass
class GpuInfo:
    used_mib: int
    total_mib: int
    ollama_mib: int
    index_note: str = ""


@dataclass
class StatusSnapshot:
    cpu_percent: float
    ram_used_bytes: int
    ram_total_bytes: int
    port_open: bool
    models: list[LoadedModel] = field(default_factory=list)
    models_error: str | None = None
    gpu: GpuInfo | None = None
    gpu_error: str | None = None
    process_names: set[str] = field(default_factory=set)
    detected_game: str | None = None
    taken_at: float = 0.0


def parse_gpu_memory_csv(text: str) -> tuple[GpuInfo | None, str | None]:
    """Parse `nvidia-smi --query-gpu=memory.used,memory.total` CSV."""
    rows: list[tuple[int, int]] = []
    for line in (text or "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        if not parts[0].isdigit() or not parts[1].isdigit():
            continue
        rows.append((int(parts[0]), int(parts[1])))
    if not rows:
        if text and "fail" in text.lower():
            return None, "The NVIDIA driver did not report video memory."
        return None, "nvidia-smi did not report video memory."
    # Show the largest card. A desktop with one RTX 4070 has one row.
    used, total = max(rows, key=lambda row: row[1])
    note = ""
    if len(rows) > 1:
        note = f"{len(rows)} GPUs found. Showing the largest."
    return GpuInfo(used_mib=used, total_mib=total, ollama_mib=0, index_note=note), None


def parse_compute_apps_csv(text: str) -> int:
    """Sum video memory held by any process whose name contains 'ollama'."""
    total = 0
    for line in (text or "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        memory = parts[-1]
        name = ",".join(parts[1:-1]).strip().lower()
        if not memory.isdigit():
            continue
        if "ollama" in name:
            total += int(memory)
    return total


def probes_paused(charts_paused: bool, defer_probes: bool) -> bool:
    """Skip the video-memory read while the window is hidden or a voice turn is open."""
    return bool(charts_paused or defer_probes)


def gpu_from_pairs(devices: list[tuple[int, int]]) -> tuple[GpuInfo | None, str | None]:
    """Pick the largest card from (used_mib, total_mib) pairs."""
    rows = [(int(used), int(total)) for used, total in devices if int(total) > 0]
    if not rows:
        return None, "The NVIDIA driver did not report video memory."
    used, total = max(rows, key=lambda row: row[1])
    note = ""
    if len(rows) > 1:
        note = f"{len(rows)} GPUs found. Showing the largest."
    return GpuInfo(used_mib=used, total_mib=total, ollama_mib=0, index_note=note), None


class _NvmlMemory(ctypes.Structure):
    _fields_ = (
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    )


_nvml_lib = None
_nvml_unavailable = False


def _load_nvml():
    """Initialize NVML once per process and reuse the library handle."""
    global _nvml_lib, _nvml_unavailable
    if _nvml_lib is not None:
        return _nvml_lib
    if _nvml_unavailable:
        return None
    try:
        if sys.platform == "win32":
            library = ctypes.WinDLL("nvml.dll")
        else:
            library = ctypes.CDLL("libnvidia-ml.so.1")
        library.nvmlInit_v2.restype = ctypes.c_int
        if library.nvmlInit_v2() != 0:
            _nvml_unavailable = True
            return None
        library.nvmlDeviceGetCount_v2.argtypes = [ctypes.POINTER(ctypes.c_uint)]
        library.nvmlDeviceGetCount_v2.restype = ctypes.c_int
        library.nvmlDeviceGetHandleByIndex_v2.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
        library.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
        library.nvmlDeviceGetMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NvmlMemory)]
        library.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int
        _nvml_lib = library
        return library
    except (OSError, AttributeError):
        _nvml_unavailable = True
        return None


def read_nvml_devices() -> list[tuple[int, int]] | None:
    """Used and total MiB from NVML. None when the driver library is missing."""
    library = _load_nvml()
    if library is None:
        return None
    try:
        count = ctypes.c_uint()
        if library.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0:
            return None
        devices: list[tuple[int, int]] = []
        for index in range(int(count.value)):
            handle = ctypes.c_void_p()
            if library.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(handle)) != 0:
                continue
            memory = _NvmlMemory()
            if library.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(memory)) != 0:
                continue
            devices.append((int(memory.used // (1024 * 1024)), int(memory.total // (1024 * 1024))))
        return devices or None
    except (OSError, AttributeError):
        return None


def format_mib(mib: int) -> str:
    if mib >= 10240:
        return f"{mib / 1024:.1f} GB"
    return f"{mib:,} MB"


def format_bytes(amount: int) -> str:
    gib = amount / (1024 ** 3)
    if gib >= 10:
        return f"{gib:.1f} GB"
    return f"{amount / (1024 ** 2):,.0f} MB"


class StatusCollector:
    def __init__(self, ollama) -> None:
        self.ollama = ollama
        self._cpu_primed = False
        self.charts_paused = False
        self.defer_probes = False
        self.nvml_reader = read_nvml_devices
        self._last_gpu: tuple[GpuInfo | None, str | None] = (None, None)
        self._pid_game_cache: dict[int, tuple[str, bool]] = {}

    def snapshot(self) -> StatusSnapshot:
        cpu = self._cpu()
        memory = psutil.virtual_memory()
        port_open = self.ollama.port_open()
        models: list[LoadedModel] = []
        models_error = None
        if port_open:
            try:
                models = self.ollama.running_models()
            except OllamaError as exc:
                models_error = str(exc)
        if probes_paused(self.charts_paused, self.defer_probes):
            gpu, gpu_error = self._last_gpu
        else:
            gpu, gpu_error = self._gpu()
            self._last_gpu = (gpu, gpu_error)
        names, detected = self._scan_processes()
        return StatusSnapshot(
            cpu_percent=cpu,
            ram_used_bytes=int(memory.used),
            ram_total_bytes=int(memory.total),
            port_open=port_open,
            models=models,
            models_error=models_error,
            gpu=gpu,
            gpu_error=gpu_error,
            process_names=names,
            detected_game=detected,
            taken_at=time.time(),
        )

    def _scan_processes(self) -> tuple[set[str], str | None]:
        """Every process name, and the first one installed where games live.

        Caches (name, is_game) per live PID so Windows does not reopen every
        process handle to inspect its executable path on every poll.
        """
        from babysitter.games import looks_like_game_path

        names: set[str] = set()
        detected: str | None = None
        seen_pids: set[int] = set()
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                info = getattr(proc, "info", None) or {}
                raw_name = info.get("name")
                if not raw_name:
                    continue
                name = str(raw_name)
                names.add(name)
                pid = info.get("pid")
                if isinstance(pid, int):
                    seen_pids.add(pid)
                    cached = self._pid_game_cache.get(pid)
                    if cached is not None and cached[0] == name:
                        is_game = cached[1]
                    else:
                        path = info.get("exe")
                        if path is None and hasattr(proc, "exe"):
                            try:
                                path = proc.exe()
                            except (psutil.Error, OSError):
                                path = ""
                        is_game = bool(path and looks_like_game_path(str(path)))
                        self._pid_game_cache[pid] = (name, is_game)
                    if detected is None and is_game:
                        detected = name
                elif detected is None:
                    path = info.get("exe")
                    if path and looks_like_game_path(str(path)):
                        detected = name
        except (psutil.Error, OSError):
            return names, detected
        if seen_pids and len(self._pid_game_cache) > len(seen_pids):
            self._pid_game_cache = {
                pid: entry for pid, entry in self._pid_game_cache.items() if pid in seen_pids
            }
        return names, detected

    def read_gpu(self) -> tuple[GpuInfo | None, str | None]:
        return self._gpu(processes=True)

    def _gpu(self, processes: bool = False) -> tuple[GpuInfo | None, str | None]:
        gpu = self._gpu_nvml()
        if gpu is not None:
            if processes:
                self._fill_ollama_mib(gpu)
            return gpu, None
        return self._gpu_smi()

    def _gpu_nvml(self) -> GpuInfo | None:
        try:
            devices = self.nvml_reader()
        except Exception:
            return None
        if not devices:
            return None
        gpu, _error = gpu_from_pairs(devices)
        return gpu

    def _cpu(self) -> float:
        if not self._cpu_primed:
            psutil.cpu_percent(interval=0.1)
            self._cpu_primed = True
        return float(psutil.cpu_percent(interval=None))

    def _fill_ollama_mib(self, gpu: GpuInfo) -> None:
        try:
            apps = run_hidden(
                [
                    "nvidia-smi",
                    "--query-compute-apps=pid,process_name,used_memory",
                    "--format=csv,noheader,nounits",
                ],
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        if apps.returncode == 0:
            gpu.ollama_mib = parse_compute_apps_csv(apps.stdout or "")

    def _gpu_smi(self) -> tuple[GpuInfo | None, str | None]:
        try:
            memory = run_hidden(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                timeout=5,
            )
        except FileNotFoundError:
            return None, "nvidia-smi was not found. Install the NVIDIA driver, which includes it."
        except subprocess.TimeoutExpired:
            return None, "nvidia-smi took too long."
        except OSError as exc:
            return None, f"Could not run nvidia-smi ({exc})."
        if memory.returncode != 0:
            detail = (memory.stderr or memory.stdout or "").strip()
            if "not found" in detail.lower() or memory.returncode == 127:
                return None, "nvidia-smi was not found."
            return None, detail[:300] or "nvidia-smi failed."
        gpu, error = parse_gpu_memory_csv(memory.stdout or "")
        if gpu is None:
            return None, error
        try:
            apps = run_hidden(
                [
                    "nvidia-smi",
                    "--query-compute-apps=pid,process_name,used_memory",
                    "--format=csv,noheader,nounits",
                ],
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            apps = None
        if apps is not None and apps.returncode == 0:
            gpu.ollama_mib = parse_compute_apps_csv(apps.stdout or "")
        return gpu, None


def placement_from_payload(payload: dict) -> list[str]:
    """Helper for tests and the model card."""
    lines = []
    for model in models_from_ps(payload):
        lines.append(f"{model.name} — {model.gpu_label}")
    return lines


def explain_gpu_hold(held_mib: int | None) -> tuple[bool | None, str]:
    """(True means Ollama still holds VRAM, False means it does not, None means unknown)."""
    if held_mib is None:
        return None, "Video memory could not be checked."
    if held_mib > 0:
        return True, f"Ollama is still using about {format_mib(held_mib)} of video memory."
    return False, "Ollama is not holding video memory."
