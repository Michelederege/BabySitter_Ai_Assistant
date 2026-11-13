"""The Windows voice that is already on the PC.

The words to speak are written to the program's input. They are never
placed on the command line. Kokoro is a later engine in this same slot.
Voice cloning is not supported.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from babysitter.platform import popen_hidden


class WindowsVoiceError(Exception):
    """The Windows voice could not speak."""


# Fixed program text. The reply is not inserted here.
_SPEAK_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$wanted = $env:BS_VOICE
if ($wanted) {
  foreach ($voice in $synth.GetInstalledVoices()) {
    if ($voice.VoiceInfo.Name -eq $wanted) {
      $synth.SelectVoice($wanted)
      break
    }
  }
}
$rate = 0
if ($env:BS_RATE) { [void][int]::TryParse($env:BS_RATE, [ref]$rate) }
if ($rate -gt 10) { $rate = 10 }
if ($rate -lt -10) { $rate = -10 }
$synth.Rate = $rate
$text = [Console]::In.ReadToEnd()
if ($text) { $synth.Speak($text) }
"""

_LIST_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }
"""


def available() -> bool:
    return sys.platform == "win32"


def speak_command() -> list[str]:
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SPEAK_SCRIPT]


class WindowsSpeaker:
    """One voice at a time. A new line, or holding Talk, stops the current one."""

    def __init__(self) -> None:
        self._proc = None
        self._lock = threading.Lock()

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()

    def speak(self, text: str, voice: str = "", rate: int = 0) -> None:
        if not available():
            raise WindowsVoiceError("The Windows voice only speaks on Windows.")
        spoken = (text or "").strip()
        if not spoken:
            return
        self.stop()
        env = os.environ.copy()
        if voice:
            env["BS_VOICE"] = voice
        env["BS_RATE"] = str(int(rate))
        proc = popen_hidden(
            speak_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
        )
        with self._lock:
            self._proc = proc
        try:
            try:
                if proc.stdin is not None:
                    proc.stdin.write(spoken.encode("utf-8"))
                    proc.stdin.close()
            except (BrokenPipeError, OSError) as exc:
                raise WindowsVoiceError("The Windows voice stopped before it could speak.") from exc
            proc.wait(timeout=90)
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None


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
