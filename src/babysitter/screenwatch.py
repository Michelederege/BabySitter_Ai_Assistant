"""Watching one monitor: which one he means, and the text on it.

"Look at monitor one" picks a monitor. From then on, each question takes a
fresh picture of that monitor, at the moment it's asked. Nothing is
recorded in between, and nothing is saved to disk. The picture is read twice:

* Windows' own text recognition (the OCR built into Windows 10 and 11, run
  on this PC) reads every word at full resolution, so small print is read
  exactly, not guessed from a shrunk picture;
* the model gets a shrunk copy of the picture for layout, colours and images,
  plus the lines of text that matter to the question.

The browser on that monitor is found the same local way: the window list,
then the address bar through Windows UI Automation. Nothing goes online here.
"""

from __future__ import annotations

import base64
import re
import subprocess
import sys
from dataclasses import dataclass

# ---------- which monitor ----------

_NUMBER_WORDS = {
    "one": 1, "first": 1, "1st": 1, "two": 2, "second": 2, "2nd": 2, "to": 2, "too": 2,
    "three": 3, "third": 3, "3rd": 3, "four": 4, "fourth": 4, "4th": 4,
}
_SCREEN = r"(?:monitor|screen|display)s?"
_PLACE_WORDS = {
    "main": "primary", "primary": "primary", "big": "primary",
    "left": "left", "right": "right", "top": "top", "upper": "top", "bottom": "bottom", "lower": "bottom",
    "vertical": "portrait", "portrait": "portrait", "tall": "portrait", "sideways": "portrait",
    "horizontal": "landscape", "landscape": "landscape", "wide": "landscape",
    "this": "cursor", "current": "cursor",
    "both": "all", "all": "all", "every": "all",
}

_WATCH_VERBS = r"(?:look at|watch|keep an eye on|keep watching|look on|see|check|use|switch to|go to|focus on|start watching)"
_WHERE = rf"(?:\s+(?:on|from|off)\s+(?:my\s+|the\s+|this\s+)?(?:(?P<word>\w+)\s+)?{_SCREEN}(?:\s+(?P<after>\w+))?)?"
_READ = re.compile(
    r"^(?:read|read out|read me|read aloud|read to me)\s+(?:me\s+)?"
    rf"(?:what'?s|what is|the text|the words|everything|all the text|what it says)?{_WHERE}$"
    rf"|^read\s+(?:my\s+|the\s+|this\s+)?(?:(?P<word2>\w+)\s+)?{_SCREEN}(?:\s+(?P<after2>\w+))?$"
    r"|^(?:what does this say|what does the screen say|what does my screen say|read this(?: to me| out| for me)?)$"
)
_COPY = re.compile(
    rf"^(?:copy|grab|get)\s+(?:the\s+|all the\s+)?(?:text|words|writing){_WHERE}$"
)
_WATCH = re.compile(
    rf"^{_WATCH_VERBS}\s+(?:my\s+|the\s+|this\s+)?(?:(?P<word>\w+)\s+)?{_SCREEN}(?:\s+(?P<after>\w+))?$"
)
_STOP = {
    "stop watching", "stop watching the screen", "stop watching my screen", "stop watching the monitor",
    "stop looking", "stop looking at the screen", "stop looking at my screen", "stop looking at the monitor",
    "stop watching my monitor", "stop screen watching", "you can stop watching", "stop reading my screen",
    "don't look at my screen", "dont look at my screen", "stop watching monitor one", "stop watching monitor two",
}
_WHICH = {
    "which monitor are you watching", "which screen are you watching", "what monitor are you watching",
    "what screen are you watching", "are you watching my screen", "are you watching the screen",
    "what are you watching", "which monitor are you looking at", "which screen are you looking at",
}
_LIST = {
    "how many monitors do i have", "how many screens do i have", "list my monitors", "list my screens",
    "what monitors do i have", "what screens do i have",
}


def monitor_spec(phrase: str) -> str | None:
    """"look at monitor one" is "1"; "watch my left screen" is "left". None when it isn't one."""
    found = _WATCH.match(phrase)
    if not found:
        return None
    for word in (found.group("after"), found.group("word")):
        if not word:
            continue
        if word.isdigit() and 0 < int(word) < 10:
            return word
        if word in _NUMBER_WORDS:
            return str(_NUMBER_WORDS[word])
        if word in _PLACE_WORDS:
            return _PLACE_WORDS[word]
    if found.group("word") in {None, "my", "the"} and not found.group("after"):
        return "cursor" if phrase.startswith(("watch", "keep")) else None
    return None


def _spec_from(word: str | None, after: str | None) -> str:
    for value in (after, word):
        if not value:
            continue
        if value.isdigit() and 0 < int(value) < 10:
            return value
        if value in _NUMBER_WORDS:
            return str(_NUMBER_WORDS[value])
        if value in _PLACE_WORDS:
            return _PLACE_WORDS[value]
    return ""


def watch_command(phrase: str):
    """(kind, spec) for a watching command, or None. An empty spec means the watched monitor."""
    read = _READ.match(phrase)
    if read:
        groups = read.groupdict()
        return "screen_read", _spec_from(groups.get("word") or groups.get("word2"), groups.get("after") or groups.get("after2"))
    copy = _COPY.match(phrase)
    if copy:
        return "screen_copy", _spec_from(copy.group("word"), copy.group("after"))
    if phrase in _STOP:
        return "unwatch", ""
    if phrase in _WHICH:
        return "watch_status", ""
    if phrase in _LIST:
        return "monitors", ""
    spec = monitor_spec(phrase)
    if spec is not None:
        return "watch", spec
    return None


@dataclass(frozen=True)
class Monitor:
    """One monitor: its Windows number, its rectangle, and Qt's index for it."""

    number: int
    x: int
    y: int
    width: int
    height: int
    primary: bool
    qt_index: int = -1

    @property
    def label(self) -> str:
        shape = "portrait" if self.height > self.width else "landscape"
        main = ", main" if self.primary else ""
        return f"monitor {self.number} ({self.width} by {self.height}, {shape}{main})"


def number_monitors(windows: list[tuple[int, int, int, int, int, bool]], qt: list[tuple[int, int, int, int]]) -> list[Monitor]:
    """Windows' numbers on Qt's screens.

    windows: (display number, x, y, width, height, primary) from Windows.
    qt: (x, y, width, height) per Qt screen, in Qt's order.
    Scaling changes sizes, never the left-to-right order, so both lists are
    sorted by position and paired. When the counts differ Qt's order is used.
    """
    if not qt:
        return []
    if len(windows) != len(qt):
        return [
            Monitor(index + 1, x, y, w, h, index == 0, index)
            for index, (x, y, w, h) in enumerate(qt)
        ]
    by_place_win = sorted(windows, key=lambda m: (m[1], m[2]))
    by_place_qt = sorted(range(len(qt)), key=lambda i: (qt[i][0], qt[i][1]))
    paired = [
        Monitor(win[0], win[1], win[2], win[3], win[4], bool(win[5]), qt_index)
        for win, qt_index in zip(by_place_win, by_place_qt)
    ]
    return sorted(paired, key=lambda m: m.number)


def pick(spec: str, monitors: list[Monitor], cursor: tuple[int, int] | None = None) -> tuple[list[Monitor], str]:
    """The monitors meant by a spec, or ([], what to say)."""
    if not monitors:
        return [], "I can't find a monitor."
    count = len(monitors)
    if spec.isdigit():
        wanted = int(spec)
        chosen = [m for m in monitors if m.number == wanted]
        if not chosen:
            plural = "monitor" if count == 1 else "monitors"
            return [], f"I only see {count} {plural}, numbered {', '.join(str(m.number) for m in monitors)}."
        return chosen, ""
    if spec == "all":
        return list(monitors), ""
    if spec == "primary":
        return [next((m for m in monitors if m.primary), monitors[0])], ""
    if spec in {"left", "right"}:
        ordered = sorted(monitors, key=lambda m: m.x + m.width / 2)
        return [ordered[0] if spec == "left" else ordered[-1]], ""
    if spec in {"top", "bottom"}:
        ordered = sorted(monitors, key=lambda m: m.y + m.height / 2)
        return [ordered[0] if spec == "top" else ordered[-1]], ""
    if spec in {"portrait", "landscape"}:
        shaped = [m for m in monitors if (m.height > m.width) == (spec == "portrait")]
        if not shaped:
            return [], f"None of your monitors is {spec}."
        return [shaped[0]], ""
    if spec == "cursor" and cursor is not None:
        x, y = cursor
        for m in monitors:
            if m.x <= x < m.x + m.width and m.y <= y < m.y + m.height:
                return [m], ""
    return [next((m for m in monitors if m.primary), monitors[0])], ""


def spoken_monitors(monitors: list[Monitor]) -> str:
    if not monitors:
        return "I can't find a monitor."
    if len(monitors) == 1:
        return "You have one monitor: " + monitors[0].label + "."
    return f"You have {len(monitors)} monitors: " + "; ".join(m.label for m in monitors) + "."


def windows_monitors() -> list[tuple[int, int, int, int, int, bool]]:
    """(display number, x, y, width, height, primary) from Windows. Empty elsewhere."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class MONITORINFOEX(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    found: list[tuple[int, int, int, int, int, bool]] = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def each(handle, _dc, _rect, _data):
        info = MONITORINFOEX()
        info.cbSize = ctypes.sizeof(MONITORINFOEX)
        if ctypes.windll.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            digits = re.findall(r"\d+", info.szDevice)
            number = int(digits[-1]) if digits else len(found) + 1
            rect = info.rcMonitor
            found.append((number, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top, bool(info.dwFlags & 1)))
        return 1

    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, proc(each), 0)
    except (OSError, AttributeError):
        return []
    # Windows' DISPLAY numbers can skip (1 and 3); number them 1, 2, … in that order.
    found.sort(key=lambda m: m[0])
    return [(index + 1, *rest) for index, (_n, *rest) in enumerate(found)]


# ---------- the text on it ----------

class ScreenError(Exception):
    pass


_OCR_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataWriter, Windows.Foundation, ContentType = WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Wait-Op($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$bytes = [Convert]::FromBase64String([Console]::In.ReadToEnd())
$stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
$writer = New-Object Windows.Storage.Streams.DataWriter($stream)
$writer.WriteBytes($bytes)
$null = Wait-Op ($writer.StoreAsync()) ([UInt32])
$null = Wait-Op ($writer.FlushAsync()) ([Boolean])
$writer.DetachStream() | Out-Null
$stream.Seek(0)
$decoder = Wait-Op ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Wait-Op ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'No Windows text recognition language is installed.' }
$result = Wait-Op ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
foreach ($line in $result.Lines) { $line.Text }
"""


def _powershell(script: str, stdin: str = "", timeout: float = 30) -> str:
    if sys.platform != "win32":
        raise ScreenError("Reading the screen's text needs Windows.")
    from babysitter.platform import run_hidden

    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        done = run_hidden(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            timeout=timeout,
            input=stdin,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired as exc:
        raise ScreenError("Reading the screen took too long.") from exc
    except OSError as exc:
        raise ScreenError(f"Windows PowerShell could not start ({exc}).") from exc
    if done.returncode != 0:
        raise ScreenError("Windows could not read the text on the screen.")
    return done.stdout


def read_text(png: bytes) -> list[str]:
    """Every line Windows' text recognition finds in a PNG, top to bottom."""
    if not png:
        return []
    out = _powershell(_OCR_SCRIPT, base64.b64encode(png).decode("ascii"))
    return [line.strip() for line in out.splitlines() if line.strip()]


_STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "is", "it", "this", "that", "what", "whats",
    "what's", "does", "do", "say", "says", "me", "my", "i", "you", "can", "could", "tell", "about", "for",
    "with", "screen", "monitor", "one", "two", "here", "there", "see", "look", "read", "which", "how", "are",
    "be", "please", "show", "where", "who", "why", "when", "was", "were", "it's", "its", "they", "their",
}


def _words(text: str) -> set[str]:
    return {word[:5] for word in re.findall(r"[a-z0-9']+", (text or "").lower()) if word not in _STOP_WORDS and len(word) > 1}


def relevant_text(lines: list[str], question: str, limit: int = 3500) -> str:
    """The screen's lines that matter to the question, in screen order, inside a character budget.

    All of it when it fits. Otherwise the lines sharing words with the
    question, each with two lines either side; with no such line, the top of
    the screen. Gaps are marked with "…".
    """
    lines = [line for line in lines if line.strip()]
    whole = "\n".join(lines)
    if len(whole) <= limit:
        return whole
    wanted = _words(question)
    scores = [len(_words(line) & wanted) for line in lines]
    if not wanted or not any(scores):
        out, used = [], 0
        for line in lines:
            if used + len(line) + 1 > limit:
                break
            out.append(line)
            used += len(line) + 1
        return "\n".join(out) + "\n…"
    keep: set[int] = set()
    used = 0
    for index in sorted(range(len(lines)), key=lambda i: (-scores[i], i)):
        if scores[index] == 0:
            break
        block = [i for i in range(index - 2, index + 3) if 0 <= i < len(lines) and i not in keep]
        cost = sum(len(lines[i]) + 1 for i in block)
        if used + cost > limit:
            continue
        keep.update(block)
        used += cost
    out: list[str] = []
    previous = -2
    for index in sorted(keep):
        if index != previous + 1 and out:
            out.append("…")
        out.append(lines[index])
        previous = index
    return "\n".join(out)


_CLEAN_WORD = re.compile(r"^[A-Za-z][a-z]{1,}$|^[A-Z]{2,}$|^\$?\d[\d.,:/%]*$")


def clean_share(text: str) -> float:
    """How much of the text reads as real words. Desktop icons over a wallpaper come out near 0.5."""
    tokens = [token.strip(".,:;()'\"!?-") for token in text.split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return 1.0
    return sum(1 for token in tokens if _CLEAN_WORD.match(token)) / len(tokens)


def screen_note(label: str, text: str) -> str:
    """What the model is told about the picture it's given."""
    if not text.strip():
        return f"The picture is {label}. Windows found no readable text on it."
    warning = ""
    if clean_share(text) < 0.62:
        warning = (
            " Much of it is garbled, probably labels over pictures or icons: go by the picture for those, "
            "and never guess a name or a word you can't read."
        )
    return (
        f"The picture is {label}, taken just now. Windows read this text on it "
        "(exact words, possibly a few recognition slips). Use it to answer, quote it exactly when asked, "
        "and say so if the answer isn't on the screen. Answer as someone looking at the screen: don't mention "
        f"this text, how it was read, or any slips in it.{warning}\n" + text
    )


# ---------- the browser on that monitor ----------

# DuckDuckGo's Windows browser first: it's the one he uses.
BROWSERS = {"duckduckgo.exe", "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "arc.exe"}
_TITLE_TAIL = re.compile(
    r"\s+[-—–]\s+(?:DuckDuckGo|Google Chrome|Microsoft​?\s*Edge|Mozilla Firefox|Brave|Opera|Vivaldi|Arc)$|"
    r"\s+and \d+ more pages?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BrowserPage:
    url: str
    title: str
    browser: str


def page_title(window_title: str) -> str:
    """"Climate - Wikipedia - Google Chrome" is "Climate - Wikipedia"."""
    title = window_title or ""
    for _ in range(2):
        title = _TITLE_TAIL.sub("", title).strip()
    return title.replace("Personal - Microsoft", "").strip(" -—–")


def clean_address(value: str) -> str:
    """The address bar's text as a full address. "en.wikipedia.org/wiki/X" gets the https scheme back."""
    text = (value or "").strip()
    if not text or " " in text:
        return ""
    if re.match(r"^[a-z][a-z0-9+.-]*://", text, re.IGNORECASE):
        return text if re.match(r"^https?:/", text, re.IGNORECASE) else ""
    if re.match(r"^[\w.-]+\.[a-z]{2,}(?:[:/?#].*)?$", text, re.IGNORECASE):
        return "https:/" + "/" + text  # the scheme a browser hides
    return ""


def _browser_windows():
    """(hwnd, exe, title, rect), front-most first: Windows lists windows top of the stack first."""
    import ctypes
    from ctypes import wintypes

    import psutil

    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            exe = psutil.Process(pid.value).name().lower()
        except Exception:
            return True
        if exe not in BROWSERS:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        found.append((int(hwnd), exe, buffer.value, (rect.left, rect.top, rect.right, rect.bottom)))
        return True

    user32.EnumWindows(each, 0)
    return found


def _overlap(rect, monitor: Monitor) -> int:
    left, top, right, bottom = rect
    width = min(right, monitor.x + monitor.width) - max(left, monitor.x)
    height = min(bottom, monitor.y + monitor.height) - max(top, monitor.y)
    return max(0, width) * max(0, height)


_ADDRESS_SCRIPT = r"""
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$el = $A::FromHandle([IntPtr]__HWND__)
$cond = New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)
$e = $el.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if ($e) { $p = $null; if ($e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$p)) { $p.Current.Value } }
"""


def browser_page(monitors: list[Monitor]) -> BrowserPage | None:
    """The front-most browser window on these monitors, and the address it shows."""
    if sys.platform != "win32" or not monitors:
        return None
    try:
        windows = _browser_windows()
    except Exception:
        return None
    for hwnd, exe, title, rect in windows:
        if not any(_overlap(rect, monitor) > 0 for monitor in monitors):
            continue
        try:
            value = _powershell(_ADDRESS_SCRIPT.replace("__HWND__", str(int(hwnd))), timeout=15).strip()
        except ScreenError:
            value = ""
        return BrowserPage(clean_address(value.splitlines()[0] if value else ""), page_title(title), exe)
    return None
