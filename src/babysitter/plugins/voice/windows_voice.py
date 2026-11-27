"""The Windows voice that is already on the PC.

The words to speak are written to the program's input. They are never
placed on the command line. Kokoro is a later engine in this same slot.
The only copied voices are the narrators and your own recording; this
voice copies no one.

One PowerShell program stays open while the voice is in use, one line in
for each sentence and "done" back when it has been said. Starting a new
one for every sentence cost about 0.4 s each (measured 27 Nov 2026), the
pause between sentences. Stop ends the program mid-word; it is started
again for the next sentence, and it closes itself after two quiet minutes.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading

from babysitter.platform import popen_hidden


class WindowsVoiceError(Exception):
    """The Windows voice could not speak."""


# Fixed program text. Replies reach it only as lines on its input:
# "<voice name>\t<rate>\t<words>". The voice is used only if installed.
_SPEAK_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$installed = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name })
$current = ''
[Console]::Out.WriteLine('ready')
[Console]::Out.Flush()
while ($null -ne ($line = [Console]::In.ReadLine())) {
  $parts = $line.Split([char]9, 3)
  if ($parts.Count -lt 3) { [Console]::Out.WriteLine('done'); [Console]::Out.Flush(); continue }
  $wanted = $parts[0]
  if ($wanted -and $wanted -ne $current -and $installed -contains $wanted) {
    $synth.SelectVoice($wanted)
    $current = $wanted
  }
  $rate = 0
  [void][int]::TryParse($parts[1], [ref]$rate)
  if ($rate -gt 10) { $rate = 10 }
  if ($rate -lt -10) { $rate = -10 }
  $synth.Rate = $rate
  if ($parts[2]) { $synth.Speak($parts[2]) }
  [Console]::Out.WriteLine('done')
  [Console]::Out.Flush()
}
"""

_LIST_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }
"""

START_SECONDS = 20
SENTENCE_SECONDS = 90
IDLE_SECONDS = 120


def available() -> bool:
    return sys.platform == "win32"


def speak_command() -> list[str]:
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SPEAK_SCRIPT]


def speak_line(text: str, voice: str = "", rate: int = 0) -> str:
    """One input line. Tabs and line breaks in the words become spaces."""
    words = " ".join((text or "").replace("\t", " ").split())
    name = " ".join((voice or "").replace("\t", " ").split())
    return f"{name}\t{int(rate)}\t{words}\n"


class WindowsSpeaker:
    """One voice at a time. A new line, or holding Talk, stops the current one."""

    def __init__(self) -> None:
        self._proc = None
        self._lines: queue.Queue | None = None
        self._lock = threading.Lock()
        self._speaking = False
        self._idle: threading.Timer | None = None
        self.cancelled = threading.Event()

    # ---- the program -----------------------------------------------------

    def _start(self):
        proc = popen_hidden(
            speak_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            from babysitter.platform import end_with_this_app

            end_with_this_app(proc)
        except Exception:  # noqa: BLE001 - quitting still closes it
            pass
        lines: queue.Queue = queue.Queue()

        def pump(stream=proc.stdout) -> None:
            try:
                for raw in stream:
                    lines.put(raw.decode("utf-8", "replace").strip())
            except (OSError, ValueError):
                pass
            finally:
                lines.put(None)

        threading.Thread(target=pump, name="babysitter-windows-voice", daemon=True).start()
        if self._wait(lines, "ready", START_SECONDS) != "ready":
            self._end(proc)
            raise WindowsVoiceError("The Windows voice did not start.")
        return proc, lines

    @staticmethod
    def _wait(lines: queue.Queue, want: str, seconds: float):
        try:
            while True:
                line = lines.get(timeout=seconds)
                if line is None or line == want:
                    return line
        except queue.Empty:
            return "timeout"

    @staticmethod
    def _end(proc) -> None:
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass

    def _close_if_idle(self) -> None:
        with self._lock:
            if self._speaking:
                return
            proc, self._proc, self._lines = self._proc, None, None
        self._end(proc)

    def close(self) -> None:
        """End the program now, speaking or not."""
        with self._lock:
            proc, self._proc, self._lines = self._proc, None, None
            timer, self._idle = self._idle, None
        if timer is not None:
            timer.cancel()
        self._end(proc)

    # ---- speaking --------------------------------------------------------

    def stop(self) -> None:
        """Cut off the sentence being said. An idle program is kept for the next one."""
        self.cancelled.set()
        with self._lock:
            speaking = self._speaking
        if speaking:
            self.close()

    def speak(self, text: str, voice: str = "", rate: int = 0) -> None:
        if not available():
            raise WindowsVoiceError("The Windows voice only speaks on Windows.")
        spoken = (text or "").strip()
        if not spoken:
            return
        self.stop()
        self.cancelled.clear()
        with self._lock:
            if self._idle is not None:
                self._idle.cancel()
                self._idle = None
            proc, lines = self._proc, self._lines
        if proc is None or proc.poll() is not None:
            proc, lines = self._start()
            with self._lock:
                self._proc, self._lines = proc, lines
        with self._lock:
            self._speaking = True
        try:
            try:
                proc.stdin.write(speak_line(spoken, voice, rate).encode("utf-8"))
                proc.stdin.flush()
            except (OSError, ValueError) as exc:
                self.close()
                if self.cancelled.is_set():
                    return
                raise WindowsVoiceError("The Windows voice stopped before it could speak.") from exc
            answer = self._wait(lines, "done", SENTENCE_SECONDS)
            if answer == "timeout":
                self.close()
                raise WindowsVoiceError("The Windows voice took too long and was stopped.")
            if answer is None and not self.cancelled.is_set():
                with self._lock:
                    if self._proc is proc:
                        self._proc, self._lines = None, None
                raise WindowsVoiceError("The Windows voice stopped before it finished.")
        finally:
            with self._lock:
                self._speaking = False
                if self._proc is not None and self._idle is None:
                    self._idle = threading.Timer(IDLE_SECONDS, self._idle_done)
                    self._idle.daemon = True
                    self._idle.start()

    def _idle_done(self) -> None:
        with self._lock:
            self._idle = None
        self._close_if_idle()


def speak_blocking(text: str, voice: str = "", rate: int = 0) -> None:
    """Speak on Windows. Used by the background voice thread."""
    speaker.speak(text, voice=voice, rate=rate)


def list_voice_names() -> list[str]:
    if not available():
        return []
    from babysitter.platform import run_hidden

    completed = run_hidden(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _LIST_SCRIPT],
        timeout=20,
    )
    names = []
    for line in (completed.stdout or "").splitlines():
        name = line.strip()
        if name and name not in names:
            names.append(name)
    return names


speaker = WindowsSpeaker()
