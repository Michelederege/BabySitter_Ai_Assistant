"""Windows details: no console windows, low priority, start-with-Windows.

On other systems the same functions exist but do the closest safe thing,
so the rest of the app can be tested without a Windows PC.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Protocol

import psutil


# Same flag as subprocess.CREATE_NO_WINDOW on Windows (0x08000000).
# A windowed app must pass this or a black console can flash open.
CREATE_NO_WINDOW = 0x08000000
SW_HIDE = 0


def hidden_creation_flags() -> int:
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW))
    return 0


def running_inside_exe() -> bool:
    """True for BabySitter.exe. False when Python is running this source."""
    return bool(getattr(sys, "frozen", False))


def library_install_command(packages: tuple[str, ...] | list[str]) -> list[str] | None:
    """pip install for a source run.

    None when this process is the exe. The exe cannot install Python
    libraries into itself, and starting it with -m pip opens another window.
    """
    if running_inside_exe():
        return None
    return [sys.executable, "-m", "pip", "install", *packages]


def missing_from_exe(feature: str) -> str:
    return (
        f"{feature} is not inside this BabySitter.exe. "
        "Build the exe again from the project folder so those programs are packed in. "
        "Nothing was downloaded."
    )


def libraries_import(*names: str) -> bool:
    """True when each library imports.

    A missing file or DLL is not an ImportError. In the packaged exe that
    used to close the window. Here it means the feature is not available.
    """
    try:
        for name in names:
            __import__(name)
    except ImportError:
        return False
    except OSError:
        try:
            from babysitter.logsetup import get_logger

            logger = get_logger()
            if logger.handlers:
                logger.exception("A packed library is missing a file: %s", ", ".join(names))
        except Exception:
            pass
        return False
    return True


def popen_hidden(args: list[str], **kwargs) -> subprocess.Popen:
    """Start a program with no console window and no shell.

    The argument list is used as-is. Model text must never be placed here.
    """
    if not args or not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise TypeError("Programs are started from a list of strings, never a shell line.")
    kwargs.pop("shell", None)
    kwargs["shell"] = False
    if sys.platform == "win32":
        flags = int(kwargs.pop("creationflags", 0))
        kwargs["creationflags"] = flags | hidden_creation_flags()
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = SW_HIDE
        kwargs["startupinfo"] = startup
    return subprocess.Popen(args, **kwargs)


_job_handle = None


def end_with_this_app(proc) -> bool:
    """Tie a started program to BabySitter, so Windows ends it when BabySitter ends.

    Used for Ollama and the natural-voice helper. Even if BabySitter crashes or is
    ended from Task Manager, no AI it started keeps running. Returns False when the
    tie could not be made (then the normal shutdown still stops it).
    """
    global _job_handle
    if sys.platform != "win32" or proc is None:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.OpenProcess.restype = wintypes.HANDLE
        if _job_handle is None:

            class _Basic(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class _Io(ctypes.Structure):
                _fields_ = [(name, ctypes.c_uint64) for name in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class _Extended(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", _Basic),
                    ("IoInfo", _Io),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            job = kernel.CreateJobObjectW(None, None)
            if not job:
                return False
            info = _Extended()
            info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
                kernel.CloseHandle(job)
                return False
            _job_handle = job
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        handle = kernel.OpenProcess(0x0100 | 0x0001, False, int(proc.pid))
        if not handle:
            return False
        try:
            return bool(kernel.AssignProcessToJobObject(_job_handle, handle))
        finally:
            kernel.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return False


def run_hidden(
    args: list[str],
    timeout: float = 8,
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a short program, capture its text, and never open a console."""
    if not args or not isinstance(args, list):
        raise TypeError("Programs are started from a list of strings, never a shell line.")
    kwargs: dict = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "shell": False,
        "stdin": subprocess.DEVNULL,
    }
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    if env is not None:
        kwargs["env"] = env
    if sys.platform == "win32":
        kwargs["creationflags"] = hidden_creation_flags()
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = SW_HIDE
        kwargs["startupinfo"] = startup
    return subprocess.run(args, **kwargs)


def mark_current_thread_efficient() -> None:
    """Ask Windows to run this idle thread at an efficient speed.

    Speech and transcription threads do not call this, so a reply stays fast.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class _Throttle(ctypes.Structure):
            _fields_ = [
                ("Version", wintypes.ULONG),
                ("ControlMask", wintypes.ULONG),
                ("StateMask", wintypes.ULONG),
            ]

        state = _Throttle(1, 0x1, 0x1)
        ctypes.windll.kernel32.SetThreadInformation(
            ctypes.windll.kernel32.GetCurrentThread(),
            3,
            ctypes.byref(state),
            ctypes.sizeof(state),
        )
    except (OSError, AttributeError):
        return


def apply_game_core_avoidance(enabled: bool) -> str:
    """Optional. Off unless the user turns it on, and only on a 24-thread CPU.

    Logical processors 12–23 are the usual second half of a Ryzen 9 7900X.
    Check frame times before leaving it on. A smaller CPU is left alone.
    """
    if not enabled:
        return ""
    count = psutil.cpu_count(logical=True) or 0
    if count < 24:
        return "Core avoidance stayed off. This PC does not have 24 logical processors."
    try:
        psutil.Process().cpu_affinity(list(range(12, min(24, count))))
    except (psutil.Error, OSError, AttributeError) as exc:
        return f"Could not set processor affinity ({exc})."
    return "BabySitter is staying on logical processors 12 to 23. Test game frame times before you leave this on."


def lower_own_priority() -> str:
    """Keep BabySitter from stealing frames from a game.

    Ollama itself is left at normal priority so a reply is not sluggish.
    """
    try:
        proc = psutil.Process()
        if sys.platform == "win32":
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            return "This app is running at below-normal priority."
        proc.nice(10)
        return "This app lowered its own CPU priority."
    except (psutil.Error, OSError, AttributeError) as exc:
        return f"Could not lower CPU priority ({exc}). The app will still run."


def set_windows_app_id() -> None:
    """So the taskbar groups BabySitter under its own icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Local.BabySitter.App"
        )
    except (OSError, AttributeError):
        pass


def prefer_per_monitor_dpi() -> None:
    """Keep the window sharp on a high-DPI monitor. Safe to skip if it fails."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        pass


class AutostartBackend(Protocol):
    def read(self, name: str) -> str | None: ...
    def write(self, name: str, command: str) -> None: ...
    def delete(self, name: str) -> None: ...


class MemoryAutostart:
    """Stand-in used in tests and on non-Windows machines."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, name: str) -> str | None:
        return self.values.get(name)

    def write(self, name: str, command: str) -> None:
        self.values[name] = command

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class WindowsRegistryAutostart:
    """The current user's Startup list. Does not need administrator rights."""

    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def _open(self, write: bool):
        import winreg

        access = winreg.KEY_SET_VALUE if write else winreg.KEY_READ
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, access)

    def read(self, name: str) -> str | None:
        import winreg

        try:
            with self._open(False) as key:
                value, _typ = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        except OSError:
            return None
        return str(value)

    def write(self, name: str, command: str) -> None:
        import winreg

        with self._open(True) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)

    def delete(self, name: str) -> None:
        import winreg

        try:
            with self._open(True) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return


def autostart_command(
    *,
    frozen: bool,
    executable: str,
    source_launcher: str | None,
) -> str:
    """Command Windows should run at login. Fixed text, never model output."""
    if frozen:
        return f'"{executable}"'
    if not source_launcher:
        raise ValueError("Starting with Windows from source needs Run BabySitter.vbs.")
    return f'wscript.exe "{source_launcher}"'


def sync_autostart(
    enabled: bool,
    command: str,
    backend: AutostartBackend,
    value_name: str = "BabySitter",
) -> None:
    if enabled:
        backend.write(value_name, command)
    else:
        backend.delete(value_name)


def default_autostart_backend() -> AutostartBackend:
    if sys.platform == "win32":
        return WindowsRegistryAutostart()
    return MemoryAutostart()


def source_launcher_path(root: Path | None = None) -> Path:
    if root is None:
        from babysitter.paths import project_root

        root = project_root()
    return root / "Run BabySitter.vbs"
