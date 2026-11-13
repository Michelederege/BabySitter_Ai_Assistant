"""Hear a keyword, then the question, on this PC.

The microphone stays open only while keyword listening is on and the AI is
on. Audio is checked in memory. It is not saved and it is not sent anywhere.
"""

from __future__ import annotations

import json
import queue
import re
import sys
import threading
import time
import zipfile
from pathlib import Path
from urllib import request as urlrequest

from babysitter.paths import data_dir
from babysitter.platform import run_hidden
from babysitter.security import require_keyword_model_url


MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
MODEL_NAME = "vosk-model-small-en-us-0.15"
KEYWORD_PACKAGES = ("vosk==0.3.45", "sounddevice==0.5.6")
DEFAULT_KEYWORD = "baby sitter"


class KeywordError(Exception):
    """The keyword listener could not start."""


def clean_keyword(text: str) -> str:
    words = re.findall(r"[a-z]+", (text or "").lower())
    if not 1 <= len(words) <= 4:
        raise KeywordError("Use one to four words, such as baby sitter.")
    if any(len(word) < 2 or len(word) > 20 for word in words):
        raise KeywordError("Each word should be between 2 and 20 letters.")
    return " ".join(words)


def _tokens(text: str) -> list[str]:
    """One form for “baby sitter” and “babysitter”."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    heard: list[str] = []
    for word in words:
        if word == "unk":
            continue
        if word == "babysitter":
            heard.extend(["baby", "sitter"])
        else:
            heard.append(word)
    return heard


def command_after_keyword(text: str, keyword: str) -> str | None:
    """Return the words spoken after the keyword in the same sentence.

    None means the keyword was not heard. An empty string means only the
    keyword was heard, so the command can still follow after a short pause.
    """
    words = _tokens(text)
    key = _tokens(clean_keyword(keyword))
    for index in range(len(words) - len(key) + 1):
        if words[index : index + len(key)] == key:
            return " ".join(words[index + len(key) :]).strip()
    return None


def model_dir() -> Path:
    return data_dir() / "models" / "vosk" / MODEL_NAME


def model_ready() -> bool:
    return (model_dir() / "conf" / "model.conf").is_file()


def packages_installed() -> bool:
    try:
        import sounddevice  # noqa: F401
        import vosk  # noqa: F401
    except ImportError:
        return False
    return True


def install_command() -> list[str]:
    return [sys.executable, "-m", "pip", "install", *KEYWORD_PACKAGES]


def install_packages() -> None:
    completed = run_hidden(install_command(), timeout=900)
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if completed.returncode not in (0, None):
        raise KeywordError(output[-1500:] or "The keyword programs did not install.")


def download_model() -> str:
    """Download the small local keyword model. The user must confirm first."""
    require_keyword_model_url(MODEL_URL)
    if not packages_installed():
        install_packages()
    if not packages_installed():
        raise KeywordError(
            "The keyword programs installed. Close BabySitter, open it again, "
            "and turn keyword listening on once more so the model can download."
        )
    destination = model_dir()
    if model_ready():
        return "Keyword listening is ready."
    destination.parent.mkdir(parents=True, exist_ok=True)
    archive = destination.parent / (MODEL_NAME + ".zip")
    try:
        urlrequest.urlretrieve(MODEL_URL, archive)  # noqa: S310  checked above
        _safe_extract(archive, destination.parent)
    finally:
        if archive.exists():
            archive.unlink()
    if not model_ready():
        raise KeywordError("The keyword model downloaded, but it was not usable.")
    return "Keyword listening is ready. Say the keyword and the command in one sentence."


def _safe_extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            parts = Path(info.filename).parts
            if not parts or ".." in parts or Path(info.filename).is_absolute():
                raise KeywordError("The model download contained an unsafe path.")
        bundle.extractall(destination)


class KeywordListener:
    """Opens the microphone for the keyword, then closes it when stopped."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, keyword: str, on_phrase, on_status, on_error) -> None:
        if self.running:
            return
        if not packages_installed() or not model_ready():
            raise KeywordError("Keyword listening is not downloaded yet.")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(clean_keyword(keyword), on_phrase, on_status, on_error),
            name="babysitter-keyword",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
        if thread is None or not thread.is_alive():
            self._thread = None

    def _run(self, keyword: str, on_phrase, on_status, on_error) -> None:
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model

            model = Model(str(model_dir()))
            audio: queue.Queue[bytes] = queue.Queue()

            def on_audio(indata, _frames, _time, status) -> None:
                if status:
                    return
                audio.put(bytes(indata))

            with sd.RawInputStream(
                samplerate=16000,
                blocksize=4000,
                dtype="int16",
                channels=1,
                callback=on_audio,
            ):
                recognizer = KaldiRecognizer(model, 16000)
                on_status("armed")
                while not self._stop.is_set():
                    try:
                        chunk = audio.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if not recognizer.AcceptWaveform(chunk):
                        continue
                    heard = json.loads(recognizer.Result()).get("text", "")
                    command = command_after_keyword(heard, keyword)
                    if command is None:
                        continue
                    if not command:
                        on_status("capturing")
                        command = self._capture_question(model, audio)
                    if command and not self._stop.is_set():
                        on_phrase(command)
                    recognizer = KaldiRecognizer(model, 16000)
                    if not self._stop.is_set():
                        on_status("armed")
        except Exception as exc:
            on_error(str(exc) or "Keyword listening stopped.")
        finally:
            self._thread = None

    def _capture_question(self, model, audio: queue.Queue[bytes]) -> str:
        from vosk import KaldiRecognizer

        recognizer = KaldiRecognizer(model, 16000)
        deadline = time.time() + 8
        while time.time() < deadline and not self._stop.is_set():
            try:
                chunk = audio.get(timeout=0.2)
            except queue.Empty:
                continue
            if recognizer.AcceptWaveform(chunk):
                text = json.loads(recognizer.Result()).get("text", "").strip()
                if text and text != "[unk]":
                    return text
        final = json.loads(recognizer.FinalResult()).get("text", "").strip()
        if final == "[unk]":
            return ""
        return final
