"""What a GitHub visit still has to get before BabySitter can talk.

The public page holds the program source. It does not hold a finished
.exe, Ollama, or the models. This module names each piece and, after a
yes, asks the local Ollama to pull the two models this app actually uses.
It does not download Python, the Ollama installer, or the NVIDIA driver.
Those files change, and this project only keeps a download it can check.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

from babysitter.intelligence import MAIN_MODEL, WRITING_MODEL


GITHUB_PAGE = "https://github.com/Michelederege/BabySitter_Ai_Assistant"
GITHUB_ZIP = GITHUB_PAGE + "/archive/refs/heads/main.zip"
PYTHON_PAGE = "https://www.python.org/downloads/windows/"
OLLAMA_PAGE = "https://ollama.com/download"

# Low, then the writing model. Nothing else is pulled from here.
REQUIRED_MODELS = (MAIN_MODEL, WRITING_MODEL)


@dataclass(frozen=True)
class Piece:
    """One thing a setup has to account for."""

    name: str
    on_github: bool
    wizard_downloads: bool
    note: str


@dataclass(frozen=True)
class Machine:
    """What this PC already has. No network call is stored here."""

    python_ok: bool
    venv_ready: bool
    ollama_exe: str | None
    # None means the list could not be read. An empty tuple means none installed.
    installed_models: tuple[str, ...] | None
    nvidia_smi: bool


def pieces() -> tuple[Piece, ...]:
    """Every piece, in the order a visitor meets them."""
    return (
        Piece(
            "program source",
            True,
            False,
            "The ZIP is the Python files, the pictures, and this list.",
        ),
        Piece(
            "requirements.txt",
            True,
            False,
            "The library names and their checksums. Not the library files.",
        ),
        Piece(
            "Python 3.12",
            False,
            False,
            "Installed from python.org. This setup does not fetch that installer.",
        ),
        Piece(
            "Python libraries",
            False,
            True,
            "pip downloads the pinned files named in requirements.txt.",
        ),
        Piece(
            "Ollama",
            False,
            False,
            "Installed from ollama.com. This setup does not fetch that installer.",
        ),
        Piece(
            MAIN_MODEL,
            False,
            True,
            "ollama pull, after you say yes.",
        ),
        Piece(
            WRITING_MODEL,
            False,
            True,
            "ollama pull, after you say yes.",
        ),
        Piece(
            "NVIDIA driver",
            False,
            False,
            "Installed from NVIDIA. This setup does not fetch it.",
        ),
        Piece(
            "voice and sharper memory",
            False,
            False,
            "The running app downloads these later, after a separate yes, and checks each file.",
        ),
    )


def visitor_summary() -> str:
    """What the GitHub page gives a visitor, and what it does not."""
    return (
        "The GitHub page "
        + GITHUB_PAGE
        + " holds the program source: the Python files, the pictures, and requirements.txt. "
        "Downloading the ZIP from "
        + GITHUB_ZIP
        + " gets that source. It does not hold a finished .exe, Ollama, or the AI models. "
        "There is no release file on that page yet. "
        "After the ZIP, this PC still needs Python 3.12 from "
        + PYTHON_PAGE
        + ", the libraries named in requirements.txt, Ollama from "
        + OLLAMA_PAGE
        + ", and two models Ollama downloads itself: "
        + MAIN_MODEL
        + " and "
        + WRITING_MODEL
        + ". The NVIDIA driver is separate, and this setup does not download it."
    )


def portable_note() -> str:
    """Why the built exe can leave the folder it was made in."""
    return (
        "The built program is one file, dist\\BabySitter.exe. "
        "Copy that file to the desktop or any other folder. "
        "The pictures travel inside the file. Settings stay in %LOCALAPPDATA%\\BabySitter, "
        "so the file does not need the folder it was built in. "
        "Start with Windows remembers the path you gave it. "
        "If you move the file, turn Start with Windows off and on again."
    )


def models_from_list_text(text: str) -> tuple[str, ...]:
    """Names from `ollama list`. The header row is skipped."""
    names: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        name = stripped.split()[0]
        if name.lower() == "name":
            continue
        names.append(name)
    return tuple(names)


def model_is_installed(name: str, installed: tuple[str, ...]) -> bool:
    wanted = name.lower()
    for have in installed:
        lowered = have.lower()
        if lowered == wanted or lowered.startswith(wanted + ":"):
            return True
    return False


def missing_models(machine: Machine) -> tuple[str, ...]:
    """Required models that are not installed. Unknown list means pull nothing."""
    if machine.installed_models is None:
        return ()
    return tuple(
        name
        for name in REQUIRED_MODELS
        if not model_is_installed(name, machine.installed_models)
    )


def pull_commands(ollama_exe: str, models: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Argument lists for ollama pull. Any other model name is refused."""
    if any(model not in REQUIRED_MODELS for model in models):
        raise ValueError(
            "BabySitter only pulls " + MAIN_MODEL + " and " + WRITING_MODEL + "."
        )
    if not models:
        return ()
    if not ollama_exe:
        raise ValueError("Ollama is not installed, so nothing was pulled.")
    return tuple((ollama_exe, "pull", model) for model in models)


def commands_for(machine: Machine) -> tuple[tuple[str, ...], ...]:
    """The pulls this PC still needs. Empty when Ollama or the list is missing."""
    missing = missing_models(machine)
    if not missing or not machine.ollama_exe:
        return ()
    return pull_commands(machine.ollama_exe, missing)


def report(machine: Machine) -> str:
    """Plain lines for the person running setup. Nothing is downloaded here."""
    lines: list[str] = []
    if not machine.python_ok:
        lines.append(
            "Python 3.12 is missing. Install it from "
            + PYTHON_PAGE
            + " and check Add python.exe to PATH. This setup does not download Python."
        )
    elif not machine.venv_ready:
        lines.append(
            "The library folder .venv is not the Python that is running. "
            "Setup.bat creates it and downloads the pinned libraries from requirements.txt."
        )
    else:
        lines.append("Python 3.12 and this folder's libraries are ready.")

    if not machine.ollama_exe:
        lines.append(
            "Ollama is not installed, or it could not be found. Install it from "
            + OLLAMA_PAGE
            + " and run this setup again. This setup does not download the Ollama installer."
        )
    else:
        lines.append("Ollama is here: " + machine.ollama_exe)

    if machine.installed_models is None:
        lines.append(
            "Ollama's model list could not be read. Nothing will be downloaded until it can."
        )
    else:
        missing = missing_models(machine)
        if not missing:
            lines.append(MAIN_MODEL + " and " + WRITING_MODEL + " are already downloaded.")
        else:
            lines.append(
                "Still to download through Ollama: "
                + " and ".join(missing)
                + ". Each one is several gigabytes. Ollama fetches them. GitHub does not have them."
            )

    if machine.nvidia_smi:
        lines.append("nvidia-smi answered, so an NVIDIA driver is installed.")
    else:
        lines.append(
            "nvidia-smi was not found. The NVIDIA driver is installed from NVIDIA, not from this setup."
        )
    lines.append(
        "Voice files and the sharper memory are optional. "
        "The app downloads those later, only after you say yes, and checks each file."
    )
    return "\n".join(lines)


def perform_pulls(machine: Machine, runner, confirmed: bool) -> tuple[str, ...]:
    """Pull the missing models only after a yes. runner receives a list of strings."""
    if not confirmed:
        return ("Nothing was downloaded.",)
    if machine.installed_models is None:
        return ("Ollama's model list could not be read. Nothing was downloaded.",)
    if not machine.ollama_exe:
        return (
            "Ollama is not installed. Nothing was downloaded. The page is " + OLLAMA_PAGE,
        )
    commands = commands_for(machine)
    if not commands:
        return ("Both models are already downloaded.",)
    lines: list[str] = []
    for command in commands:
        code = runner(list(command))
        if code != 0:
            lines.append(command[-1] + " did not finish. Nothing else was downloaded.")
            break
        lines.append("Downloaded " + command[-1] + ".")
    return tuple(lines)


def probe_this_pc() -> Machine:
    """Look at this PC. Listing models talks to the local Ollama only."""
    from babysitter.ollama import find_ollama_executable
    from babysitter.platform import run_hidden

    exe = find_ollama_executable()
    installed: tuple[str, ...] | None
    if not exe:
        installed = ()
    else:
        try:
            completed = run_hidden([exe, "list"], timeout=20)
        except (OSError, subprocess.SubprocessError):
            installed = None
        else:
            if completed.returncode != 0:
                installed = None
            else:
                installed = models_from_list_text(completed.stdout or "")
    return Machine(
        python_ok=sys.version_info[:2] == (3, 12),
        venv_ready=sys.prefix != sys.base_prefix,
        ollama_exe=exe,
        installed_models=installed,
        nvidia_smi=shutil.which("nvidia-smi") is not None,
    )


def _run_pull(command: list[str]) -> int:
    completed = subprocess.run(command, shell=False)
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    machine = probe_this_pc()
    if "--pull" not in args:
        print(visitor_summary())
        print()
        print(report(machine))
        print()
        print(portable_note())
        return 0
    lines = perform_pulls(machine, _run_pull, "--yes" in args)
    for line in lines:
        print(line)
    if any(line.endswith("did not finish. Nothing else was downloaded.") for line in lines):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
