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
from babysitter.security import require_keyword_model_url, require_matching_file


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


def _recognizer(model):
    from vosk import KaldiRecognizer

    recognizer = KaldiRecognizer(model, 16000)
    tune = getattr(recognizer, "SetEndpointerDelays", None)
    if callable(tune):
        # 0.35s of quiet ends the question, instead of waiting a full second.
        tune(5.0, 0.35, 15.0)
    return recognizer


def _followup_heard(text: str) -> bool:
    from babysitter.plugins.voice.speech import followup_phrase

    return followup_phrase(text) is not None


def _yes_or_no(text: str) -> bool:
    from babysitter.plugins.voice.speech import more_answer

    return more_answer(text) in {"yes", "no"}


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
        try:
            require_matching_file(MODEL_URL, archive)
        except ValueError as exc:
            raise KeywordError(str(exc)) from None
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
        self._yes_no = False
        self._followup = False
        self.vad_enabled = False
        self.smart_turn = False
        self.echo_cancel = False
        self.talk_over = False
        self._hot = 0

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

    def expect_yes_no(self, enabled: bool) -> None:
        """After an offer of more, a plain yes or no counts without the keyword."""
        self._yes_no = bool(enabled)

    def expect_followup(self, enabled: bool) -> None:
        """For a few seconds, a normal sentence counts without the keyword."""
        self._followup = bool(enabled)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
        if thread is None or not thread.is_alive():
            self._thread = None

    def _run(self, keyword: str, on_phrase, on_status, on_error) -> None:
        from babysitter.platform import mark_current_thread_efficient

        mark_current_thread_efficient()
        try:
            import sounddevice as sd
            from vosk import Model

            model = Model(str(model_dir()))
            self._ensure_vad()
            audio: queue.Queue[bytes] = queue.Queue()

            def on_audio(indata, _frames, _time, status) -> None:
                if status:
                    return
                audio.put(bytes(indata))

            with sd.RawInputStream(
                samplerate=16000,
                blocksize=800,
                dtype="int16",
                channels=1,
                callback=on_audio,
            ):
                recognizer = _recognizer(model)
                utterance = bytearray()
                quiet_gaps = 0
                on_status("armed")
                while not self._stop.is_set():
                    try:
                        chunk = audio.get(timeout=0.2)
                        quiet_gaps = 0
                    except queue.Empty:
                        # The callback delivers silence too. A long gap means the stream died.
                        quiet_gaps += 1
                        if quiet_gaps >= 15:
                            on_status("restart")
                            break
                        continue
                    utterance.extend(chunk)
                    if len(utterance) > 16000 * 2 * 20:
                        del utterance[: len(utterance) - (16000 * 2 * 20)]
                    chunk, echoed = self._hear(chunk)
                    if echoed and self._barge(chunk):
                        on_status("talk_over")
                        continue
                    if not recognizer.AcceptWaveform(chunk):
                        continue
                    clip = bytes(utterance)
                    utterance.clear()
                    heard = json.loads(recognizer.Result()).get("text", "")
                    command = command_after_keyword(heard, keyword)
                    if command is None:
                        if self._followup and _followup_heard(heard):
                            on_phrase(heard, _wav_bytes(clip))
                            recognizer = _recognizer(model)
                            if not self._stop.is_set():
                                on_status("armed")
                            continue
                        if self._yes_no and _yes_or_no(heard):
                            on_phrase(heard, _wav_bytes(clip))
                            recognizer = _recognizer(model)
                            if not self._stop.is_set():
                                on_status("armed")
                        continue
                    if not command:
                        on_status("capturing")
                        command, clip = self._capture_question(model, audio)
                    if command and not self._stop.is_set():
                        on_phrase(command, _wav_bytes(clip))
                    recognizer = _recognizer(model)
                    if not self._stop.is_set():
                        on_status("armed")
        except Exception as exc:
            on_error(str(exc) or "Keyword listening stopped.")
        finally:
            self._thread = None

    def _ensure_vad(self) -> None:
        if not self.vad_enabled:
            self._vad = None
            return
        from babysitter.paths import data_dir
        from babysitter.plugins.voice.turntaking import open_vad

        self._vad = open_vad(True, data_dir() / "models" / "silero" / "silero_vad.onnx")

    def _speech(self, chunk: bytes) -> bool:
        vad = getattr(self, "_vad", None)
        if vad is not None:
            return bool(vad.speech(chunk))
        from babysitter.plugins.voice.turntaking import is_speech

        return is_speech(chunk)

    def _hear(self, chunk: bytes) -> tuple[bytes, bool]:
        from babysitter.plugins.voice.playback import latest_playback
        from babysitter.plugins.voice.turntaking import prepare_chunk

        if not self.echo_cancel and not self.talk_over and not self.vad_enabled:
            return chunk, False
        return prepare_chunk(chunk, self.echo_cancel, latest_playback())

    def _barge(self, chunk: bytes) -> bool:
        from babysitter.plugins.voice.turntaking import barge_in, rms

        tripped, self._hot = barge_in(rms(chunk), True, self.talk_over, self._hot)
        return tripped

    def _capture_question(self, model, audio: queue.Queue[bytes]) -> tuple[str, bytes]:
        from babysitter.plugins.voice.turntaking import endpoint_delays, finished_by_silence

        recognizer = _recognizer(model)
        delays = endpoint_delays(self.smart_turn, 0)
        tune = getattr(recognizer, "SetEndpointerDelays", None)
        if delays and callable(tune):
            tune(*delays)
        deadline = time.time() + 8
        quiet = 0
        heard_words = 0
        captured = bytearray()
        while time.time() < deadline and not self._stop.is_set():
            try:
                chunk = audio.get(timeout=0.2)
            except queue.Empty:
                continue
            captured.extend(chunk)
            chunk, _echoed = self._hear(chunk)
            if self.vad_enabled or self.smart_turn:
                if self._speech(chunk):
                    quiet = 0
                else:
                    quiet += 1
            if recognizer.AcceptWaveform(chunk):
                text = json.loads(recognizer.Result()).get("text", "").strip()
                if text and text != "[unk]":
                    return text, bytes(captured)
            partial = ""
            partial_fn = getattr(recognizer, "PartialResult", None)
            if callable(partial_fn):
                try:
                    partial = json.loads(partial_fn()).get("partial", "")
                except (json.JSONDecodeError, TypeError):
                    partial = ""
            heard_words = len([word for word in partial.split() if word])
            if self.smart_turn and heard_words:
                again = endpoint_delays(True, heard_words)
                if again and callable(tune):
                    tune(*again)
            if finished_by_silence(quiet, heard_words, self.smart_turn, self.vad_enabled):
                break
        final = json.loads(recognizer.FinalResult()).get("text", "").strip()
        if final == "[unk]":
            return "", bytes(captured)
        return final, bytes(captured)


def _wav_bytes(pcm: bytes) -> bytes:
    from babysitter.plugins.voice.hearing import pcm16_to_wav

    return pcm16_to_wav(pcm)
