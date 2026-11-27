"""Natural voices: real narrators, through the Chatterbox helper.

The helper (voiceclone_worker.py) runs in its own Python, because
Chatterbox needs numpy 1.x and its own torch. It starts the first time a
natural voice speaks, stays loaded while the AI is on, and is closed when
the AI turns off or game mode starts, so its video memory goes back.

It needs about 3.8 GB of video memory. While a natural voice is chosen the
AI runs on Low so both fit; if the card still lacks the room, the reply is
spoken with Kokoro instead and the reason is said once.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import threading
from pathlib import Path

from babysitter.paths import data_dir

NEEDS_MIB = 4000  # Chatterbox, measured at about 3.8 GB on an RTX 4070
TORCH_INDEX = "https://download.pytorch.org/whl/cu124"
PACKAGES = ("torch==2.6.0", "torchaudio==2.6.0")
CHATTERBOX = ("chatterbox-tts==0.1.7", "psutil==7.0.0")


class CloneError(Exception):
    """The natural voice could not speak. The message says what to do."""


def env_python() -> Path:
    return data_dir() / "voiceclone" / "venv" / "Scripts" / ("python.exe" if sys.platform == "win32" else "python")


def worker_script() -> Path:
    """The helper as a plain file. Inside BabySitter.exe it is unpacked under _MEIPASS."""
    packed = getattr(sys, "_MEIPASS", "")
    if packed:
        candidate = Path(packed) / "babysitter" / "voiceclone_worker.py"
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[2] / "voiceclone_worker.py"


def environment_ready() -> bool:
    return env_python().is_file()


def install_steps() -> list[list[str]]:
    """The commands that set up the helper's own Python. Run only after a yes."""
    python = str(env_python())
    return [
        ["py", "-3.12", "-m", "venv", str(env_python().parents[1])],
        [python, "-m", "pip", "install", *PACKAGES, "--index-url", TORCH_INDEX],
        [python, "-m", "pip", "install", *CHATTERBOX],
    ]


class _Worker:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._next = 0

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, model_dir: Path) -> None:
        from babysitter.platform import popen_hidden

        if self.running():
            return
        log = data_dir() / "logs" / "natural-voice.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        # -I: isolated, so BabySitter's own files (secrets.py, platform.py) never
        # stand in for Python's modules of the same name inside the helper.
        self._proc = popen_hidden(
            [str(env_python()), "-I", str(worker_script()), str(model_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=open(log, "ab"),
            text=True,
            encoding="utf-8",
        )
        from babysitter.platform import end_with_this_app

        end_with_this_app(self._proc)
        first = self._proc.stdout.readline() if self._proc.stdout else ""
        try:
            hello = json.loads(first)
        except ValueError:
            hello = {"ready": False, "error": "The natural voice did not start. Its log is in the BabySitter logs folder."}
        if not hello.get("ready"):
            self.stop()
            raise CloneError(str(hello.get("error") or "The natural voice did not start."))

    def speak(self, text: str, clip: Path, exaggeration: float = 0.5):
        import numpy as np

        with self._lock:
            if not self.running():
                raise CloneError("The natural voice is not running.")
            self._next += 1
            job = {"id": self._next, "text": text, "voice": str(clip), "exaggeration": exaggeration}
            self._proc.stdin.write(json.dumps(job) + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
        if not line:
            self.stop()
            raise CloneError("The natural voice stopped. Kokoro speaks instead.")
        reply = json.loads(line)
        if "error" in reply:
            raise CloneError(f"The natural voice could not say that ({reply['error'][:120]}).")
        samples = np.frombuffer(base64.b64decode(reply["samples"]), dtype=np.float32)
        return samples, int(reply["rate"])

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


_worker = _Worker()


def release() -> None:
    """Close the helper, so its video memory goes back to the card."""
    _worker.stop()


def ready(narrator_id: str) -> bool:
    from babysitter.modelpacks import ready as pack_ready
    from babysitter.narrators import BY_ID, clip_ready

    narrator = BY_ID.get(narrator_id)
    return narrator is not None and environment_ready() and pack_ready("chatterbox") and clip_ready(narrator)


def render(narrator_id: str, text: str, free_mib: int | None = None):
    """One sentence in a narrator's voice, as (float32 samples, sample rate)."""
    from babysitter.modelpacks import PackError, verify
    from babysitter.narrators import BY_ID, NarratorError, verified_clip

    narrator = BY_ID.get(narrator_id)
    if narrator is None or not ready(narrator_id):
        raise CloneError("The natural voices are not set up yet. Set them up on the Voice and hearing section.")
    if not _worker.running():
        if free_mib is not None and free_mib < NEEDS_MIB:
            raise CloneError(
                f"The natural voice needs about {NEEDS_MIB // 1000} GB of video memory and only "
                f"{free_mib:,} MB is free, so Kokoro speaks instead."
            )
        try:
            model_dir = verify("chatterbox")
        except PackError as exc:
            raise CloneError(str(exc)) from None
        _worker.start(model_dir)
    try:
        clip = verified_clip(narrator)
    except NarratorError as exc:
        raise CloneError(str(exc)) from None
    return _worker.speak(text, clip)


def warm(narrator_id: str, free_mib: int | None = None) -> bool:
    """Load the helper ahead of the first reply. Loading takes about 20 seconds."""
    from babysitter.modelpacks import PackError, verify

    if _worker.running() or not ready(narrator_id):
        return _worker.running()
    if free_mib is not None and free_mib < NEEDS_MIB:
        return False
    try:
        _worker.start(verify("chatterbox"))
    except (CloneError, PackError):
        return False
    return True
