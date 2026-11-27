"""Hear a keyword, then the question, on this PC.

The microphone stays open only while keyword listening is on and the AI is
on. Audio is checked in memory. It is not saved and it is not sent anywhere.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path
from urllib import request as urlrequest

from babysitter.paths import data_dir
from babysitter.platform import missing_from_exe, run_hidden, running_inside_exe
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
    if len(key) == 1:
        # A name the small keyword model does not know is heard as a sound-alike:
        # "kari" came back as corey, carly, or kyrie in every test (27 Nov).
        after = _after_sound_alike(words, key[0])
        if after is not None:
            return after
    return _after_nickname(words)


_OPENERS = {"hey", "hi", "he", "okay", "ok", "a", "hay", "hello"}


def _sound_key(word: str) -> str:
    """A rough spoken form: letters that sound alike are made the same."""
    text = (word or "").lower()
    for source, target in (("ph", "f"), ("ck", "k"), ("qu", "kw"), ("x", "ks"), ("c", "k"), ("q", "k"), ("z", "s"), ("y", "i")):
        text = text.replace(source, target)
    out = []
    for character in text:
        if not out or character != out[-1]:
            out.append(character)  # "carry" and "cary" sound the same
    return "".join(out)


def sounds_like(heard: str, name: str) -> bool:
    """True when a heard word is close enough in sound to the name."""
    from difflib import SequenceMatcher

    a, b = _sound_key(heard), _sound_key(name)
    if not a or not b or a[0] != b[0] or abs(len(a) - len(b)) > 2:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.66


def _after_sound_alike(words: list[str], name: str) -> str | None:
    """Only at the start of the sentence, after an optional "hey", so the name in
    the middle of a sentence never wakes it."""
    start = 1 if words[:1] and words[0] in _OPENERS and len(words) > 1 else 0
    # The heard word must be at least as long as the name, so "car keys" is not "Kari".
    if len(words) > start and len(_sound_key(words[start])) >= len(_sound_key(name)) and sounds_like(words[start], name):
        return " ".join(words[start + 1 :]).strip()
    # "Hey Kari" heard as "he car": the opener and part of the name run together.
    if start == 1 and sounds_like(words[0] + words[1], "hey" + name):
        return " ".join(words[2:]).strip()
    return None


def _nickname_tokens() -> list[str]:
    try:
        from babysitter.personality import persona_name

        return _tokens(persona_name())
    except Exception:  # noqa: BLE001
        return []


def _after_nickname(words: list[str]) -> str | None:
    """The nickname you gave works as a keyword too, at the start: "Jarvis, ..." or "hey Jarvis, ...".

    Only at the start, so a name said in the middle of a sentence does not wake it.
    """
    name = _nickname_tokens()
    if not name:
        return None
    start = 1 if words[:1] in (["hey"], ["okay"], ["ok"], ["hi"]) else 0
    if words[start : start + len(name)] == name:
        return " ".join(words[start + len(name) :]).strip()
    if len(name) == 1:
        return _after_sound_alike(words, name[0])
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


class SilenceWatch:
    """Notices a microphone that sends only exact silence, once, after about 6 seconds."""

    SECONDS = 6.0

    def __init__(self, rate: int = 16000) -> None:
        self._need = int(rate * self.SECONDS)
        self._seen = 0
        self._done = False

    def add(self, chunk: bytes) -> bool:
        """True once, the moment the silence is long enough to be a dead microphone."""
        if self._done or not chunk:
            return False
        import numpy as np

        samples = np.frombuffer(chunk[: len(chunk) - len(chunk) % 2], dtype=np.int16)
        if samples.size and int(np.abs(samples.astype(np.int32)).max()) > 3:
            self._done = True  # real sound: this microphone works
            return False
        self._seen += samples.size
        if self._seen >= self._need:
            self._done = True
            return True
        return False


def should_join_listener(already_requested: bool, alive: bool) -> bool:
    """A burst of stops waits once. Later stops leave the thread to exit."""
    return alive and not already_requested


def offer_audio(audio: queue.Queue, chunk: bytes) -> None:
    """Keep the newest samples. A full queue drops the oldest chunk, not this one.

    PortAudio can set a status flag on overflow. The samples in that callback
    are still the sound, so the caller keeps them.
    """
    if not chunk:
        return
    try:
        audio.put_nowait(chunk)
    except queue.Full:
        try:
            audio.get_nowait()
        except queue.Empty:
            return
        try:
            audio.put_nowait(chunk)
        except queue.Full:
            return


def model_dir() -> Path:
    return data_dir() / "models" / "vosk" / MODEL_NAME


def model_ready() -> bool:
    return (model_dir() / "conf" / "model.conf").is_file()


# Vosk opens these by name from its own folder. PyInstaller may unpack them
# at the top of the temp folder instead.
_VOSK_DLLS = (
    "libvosk.dll",
    "libgcc_s_seh-1.dll",
    "libstdc++-6.dll",
    "libwinpthread-1.dll",
)


def stage_vosk_libraries(root: str) -> None:
    """Put libvosk.dll in the vosk folder Vosk opens.

    The packaged exe can unpack those libraries at the top of the temp
    folder. Vosk joins its own folder with libvosk.dll. It does not search
    the temp folder, and Windows then says that vosk folder does not exist.
    """
    if not root:
        return
    folder = os.path.join(root, "vosk")
    if os.path.isfile(os.path.join(folder, "libvosk.dll")):
        return
    source = ""
    for candidate in (root, os.path.join(root, "bin")):
        if os.path.isfile(os.path.join(candidate, "libvosk.dll")):
            source = candidate
            break
    if not source or os.path.normcase(source) == os.path.normcase(folder):
        return
    os.makedirs(folder, exist_ok=True)
    for name in _VOSK_DLLS:
        src = os.path.join(source, name)
        dest = os.path.join(folder, name)
        if os.path.isfile(src) and not os.path.isfile(dest):
            shutil.copy2(src, dest)


def vosk_dll_directory(path: str) -> str:
    """The real folder that holds libvosk.

    The packaged exe reports the vosk folder inside a temp path. That folder
    is not written to disk unless the libraries were packed beside it. Windows
    then refuses to open the program. A real install already has the folder.
    """
    if os.path.isdir(path):
        return path
    root = getattr(sys, "_MEIPASS", "")
    if root:
        bundled = os.path.join(root, "vosk")
        if os.path.isdir(bundled):
            return bundled
        if os.path.isdir(root):
            return root
    raise FileNotFoundError(path)


def _import_vosk():
    import os

    root = getattr(sys, "_MEIPASS", "")
    if root:
        stage_vosk_libraries(root)
    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        import vosk

        return vosk
    original = os.add_dll_directory

    def add_dll_directory(path):
        return original(vosk_dll_directory(os.fspath(path)))

    os.add_dll_directory = add_dll_directory
    try:
        import vosk
    finally:
        os.add_dll_directory = original
    return vosk


def packages_installed() -> bool:
    try:
        import sounddevice  # noqa: F401

        _import_vosk()
    except (ImportError, OSError):
        return False
    return True


def install_command() -> list[str]:
    return [sys.executable, "-m", "pip", "install", *KEYWORD_PACKAGES]


def install_packages() -> None:
    if running_inside_exe():
        raise KeywordError(missing_from_exe("Keyword listening"))
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
        # urlretrieve has no timeout, so a stalled connection hung the
        # download for good. Read in pieces with a timeout instead.
        with urlrequest.urlopen(MODEL_URL, timeout=180) as response, archive.open("wb") as handle:  # noqa: S310  checked above
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
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
        self._deaths = 0
        self._stop_requested = False
        # A sounddevice index, or None for Windows' default microphone.
        self.device: int | None = None

    @property
    def running(self) -> bool:
        """A listener that is alive and not on its way out."""
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start(self, keyword: str, on_phrase, on_status, on_error) -> None:
        if self.running:
            return
        if not packages_installed() or not model_ready():
            raise KeywordError("Keyword listening is not downloaded yet.")
        # Each listener gets its own stop flag. Off then On quickly used to
        # find the old one still closing, call it "running", and do nothing,
        # so listening ended up off; clearing one shared flag instead would
        # keep the old one running beside the new. The old one keeps its own
        # set flag and ends by itself.
        self._stop = threading.Event()
        self._stop_requested = False
        self._thread = threading.Thread(
            target=self._run,
            args=(clean_keyword(keyword), on_phrase, on_status, on_error, self._stop),
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
        if thread is None or thread is threading.current_thread():
            return
        alive = thread.is_alive()
        if should_join_listener(self._stop_requested, alive):
            self._stop_requested = True
            thread.join(timeout=0.2)
            alive = thread.is_alive()
        if not alive:
            self._thread = None
            self._stop_requested = False

    def _run(self, keyword: str, on_phrase, on_status, on_error, stop: threading.Event | None = None) -> None:
        from babysitter.platform import mark_current_thread_efficient

        mark_current_thread_efficient()
        stop = stop if stop is not None else self._stop
        died = False
        try:
            import sounddevice as sd
            from vosk import Model

            model = Model(str(model_dir()))
            self._ensure_vad()
            audio: queue.Queue[bytes] = queue.Queue(maxsize=600)

            def on_audio(indata, _frames, _time, status) -> None:
                del status
                offer_audio(audio, bytes(indata))

            with sd.RawInputStream(
                samplerate=16000,
                blocksize=800,
                dtype="int16",
                channels=1,
                callback=on_audio,
                device=self.device,
            ):
                recognizer = _recognizer(model)
                utterance = bytearray()
                quiet_gaps = 0
                silence = SilenceWatch()
                on_status("armed")
                while not stop.is_set():
                    try:
                        chunk = audio.get(timeout=0.2)
                        quiet_gaps = 0
                        self._deaths = 0
                    except queue.Empty:
                        # The callback delivers silence too. A long gap means the stream died.
                        quiet_gaps += 1
                        if quiet_gaps >= 15:
                            died = True
                            break
                        continue
                    if silence.add(chunk):
                        on_status("silent")
                    utterance.extend(chunk)
                    if len(utterance) > 16000 * 2 * 20:
                        del utterance[: len(utterance) - (16000 * 2 * 20)]
                    chunk, echoed = self._hear(chunk)
                    if echoed and self._barge(chunk):
                        # Once per interruption; the words that interrupted
                        # still go to the recognizer. Before 0.28.1 every loud
                        # chunk after the third was dropped, so the sentence
                        # spoken over the voice was never heard.
                        self._hot = 0
                        on_status("talk_over")
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
                            if not stop.is_set():
                                on_status("armed")
                            continue
                        if self._yes_no and _yes_or_no(heard):
                            on_phrase(heard, _wav_bytes(clip))
                            recognizer = _recognizer(model)
                            if not stop.is_set():
                                on_status("armed")
                        continue
                    if not command:
                        on_status("capturing")
                        command, clip = self._capture_question(model, audio, stop)
                    if command and not stop.is_set():
                        on_phrase(command, _wav_bytes(clip))
                    recognizer = _recognizer(model)
                    if not stop.is_set():
                        on_status("armed")
        except Exception as exc:
            on_error(str(exc) or "Keyword listening stopped.")
        finally:
            # Only forget the thread if it is still this one. Off then On in
            # quick succession starts a new listener before this one ends;
            # clearing it here made `running` False while the new one ran, so
            # the next start opened a second microphone stream.
            if self._thread is threading.current_thread():
                self._thread = None
            if died and not stop.is_set():
                self._deaths += 1
                on_status("restart" if self._deaths < 3 else "microphone")

    def _ensure_vad(self) -> None:
        if not self.vad_enabled:
            self._vad = None
            return
        from babysitter.paths import data_dir
        from babysitter.plugins.voice.turntaking import open_vad

        silero = data_dir() / "models" / "silero" / "silero_vad.onnx"
        try:
            from babysitter.plugins.voice.silero_model import SILERO_URL
            from babysitter.security import require_loaded_file

            if silero.is_file():
                require_loaded_file(SILERO_URL, silero)
        except (ValueError, OSError):
            # A Silero file that does not match is left unused. The quiet-versus-loud check runs instead.
            silero = data_dir() / "models" / "silero" / "missing.onnx"
        self._vad = open_vad(True, silero)

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

    def _capture_question(self, model, audio: queue.Queue[bytes], stop: threading.Event | None = None) -> tuple[str, bytes]:
        from babysitter.plugins.voice.turntaking import endpoint_delays, finished_by_silence

        stop = stop if stop is not None else self._stop
        recognizer = _recognizer(model)
        delays = endpoint_delays(self.smart_turn, 0)
        tune = getattr(recognizer, "SetEndpointerDelays", None)
        if delays and callable(tune):
            tune(*delays)
        deadline = time.time() + 8
        quiet = 0
        heard_words = 0
        captured = bytearray()
        while time.time() < deadline and not stop.is_set():
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


def strip_wake(text: str, keyword: str) -> str:
    """The sentence without the keyword or nickname it starts with, capitals kept.

    After the keyword wakes it, the clip is heard again in full, so the line
    reads "Kari, what time is it?". Quick commands match "what time is it",
    so the name in front is dropped here. A sentence that does not start with
    the name is returned as it was.
    """
    original = (text or "").strip()
    words = original.split()
    for count in (1, 2, 3, 4):
        if count >= len(words):
            break
        head = " ".join(words[:count])
        try:
            rest = command_after_keyword(head, keyword)
        except KeywordError:
            return original
        if rest == "":
            return _strip_trailing_name(" ".join(words[count:]).lstrip(" ,.!?:;-"), keyword)
    return _strip_trailing_name(original, keyword)


def _strip_trailing_name(text: str, keyword: str) -> str:
    """ "Good morning, Kari" and "thanks Kari" end with the name. Quick commands
    match "good morning", so a name at the very end is dropped as well. Only an
    exact name is dropped there, never a sound-alike, so "call Corey" stays whole."""
    words = text.split()
    plain = [re.sub(r"[^a-z']", "", word.lower()) for word in words]
    keyword_tokens = _tokens(keyword)
    while keyword_tokens[:1] and keyword_tokens[0] in _OPENERS:
        keyword_tokens = keyword_tokens[1:]  # "hey Kari" ends a sentence as "Kari"
    for name in (keyword_tokens, _nickname_tokens()):
        if name and len(words) > len(name) and plain[-len(name):] == name:
            return " ".join(words[: -len(name)]).rstrip(" ,.!?:;-")
    return text
