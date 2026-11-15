"""Find files in the folders you chose. Read-only, on this PC.

"Find my tax pdf" looks in Documents, Downloads, Desktop, and any folder
you added in Settings. "Current" or "latest" means the file Windows'
own Recent list says you opened last, falling back to the newest change.
A partial name is fine: every match is listed, never an error. Opening a
file works the same way as a double-click, and only a file this search
just listed can be opened. Nothing is indexed in the background, nothing
is written, and no name leaves this PC.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


MAX_FILES = 50_000
MAX_DEPTH = 6
CACHE_SECONDS = 300

SKIP_FOLDERS = {"node_modules", "__pycache__", "appdata", "venv", ".venv"}

# Words that point at a kind of file instead of its name.
EXTENSION_WORDS = {
    "stl", "3mf", "obj", "step", "stp", "gcode", "blend",
    "pdf", "txt", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv",
    "png", "jpg", "jpeg", "gif", "svg", "heic", "webp", "psd",
    "mp4", "mov", "webm", "mkv", "mp3", "wav", "flac",
    "zip", "7z", "rar", "iso", "json", "xml",
}

# Words about wanting a file, not part of its name.
FILLER_WORDS = {
    "a", "an", "all", "my", "the", "file", "files", "folder", "that",
    "latest", "newest", "current", "recent", "last", "most", "open",
    "up", "me", "for", "of", "this", "one",
    "find", "pull", "show", "get", "give", "locate", "look", "search",
}


@dataclass(frozen=True)
class FoundFile:
    name: str
    path: str
    modified: float
    opened: float = 0.0

    @property
    def last_used(self) -> float:
        return max(self.modified, self.opened)


def default_folders(home: Path | None = None) -> list[str]:
    """Documents, Downloads, and Desktop — and their OneDrive homes.

    On many Windows PCs, Documents and Desktop actually live under
    OneDrive. A folder that does not exist is skipped by the scan, so
    naming both costs nothing on PCs without it.
    """
    base = Path(home) if home else Path.home()
    folders = [str(base / name) for name in ("Documents", "Downloads", "Desktop")]
    folders += [str(base / "OneDrive" / name) for name in ("Documents", "Desktop")]
    return folders


def scan_folders(folders: list[str]) -> list[FoundFile]:
    found: list[FoundFile] = []
    seen: set[str] = set()
    for folder in folders:
        root = Path(folder).expanduser()
        key = str(root).lower()
        if key in seen or not root.is_dir():
            continue
        seen.add(key)
        _walk(str(root), 0, found)
        if len(found) >= MAX_FILES:
            break
    return found


def _walk(folder: str, depth: int, found: list[FoundFile]) -> None:
    if depth > MAX_DEPTH or len(found) >= MAX_FILES:
        return
    try:
        entries = os.scandir(folder)
    except OSError:
        return
    with entries:
        for entry in entries:
            if len(found) >= MAX_FILES:
                return
            name = entry.name
            if name.startswith("."):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if name.lower() not in SKIP_FOLDERS:
                        _walk(entry.path, depth + 1, found)
                elif entry.is_file(follow_symlinks=False):
                    found.append(
                        FoundFile(
                            name,
                            entry.path,
                            float(entry.stat(follow_symlinks=False).st_mtime),
                        )
                    )
            except OSError:
                continue


def recently_opened() -> dict[str, float]:
    """When Windows' own Recent list last saw each file name. Empty elsewhere.

    Explorer keeps one small shortcut per opened file. Only the shortcut's
    name and date are read; the shortcut itself is never followed.
    """
    if sys.platform != "win32":
        return {}
    base = os.environ.get("APPDATA", "")
    recent = Path(base) / "Microsoft" / "Windows" / "Recent"
    if not base or not recent.is_dir():
        return {}
    opened: dict[str, float] = {}
    try:
        with os.scandir(recent) as entries:
            for entry in entries:
                if not entry.name.lower().endswith(".lnk"):
                    continue
                stem = entry.name[:-4].lower()
                try:
                    moment = float(entry.stat().st_mtime)
                except OSError:
                    continue
                opened[stem] = max(opened.get(stem, 0.0), moment)
    except OSError:
        return opened
    return opened


def parse_query(text: str) -> tuple[list[str], set[str]]:
    """The name words, and the file kinds, from a spoken request."""
    tokens = re.findall(r"[a-z0-9']+", (text or "").lower())
    words: list[str] = []
    extensions: set[str] = set()
    for token in tokens:
        singular = token[:-1] if token.endswith("s") and len(token) > 2 else token
        if token in EXTENSION_WORDS:
            extensions.add("." + token)
        elif singular in EXTENSION_WORDS:
            extensions.add("." + singular)
        elif token not in FILLER_WORDS:
            words.append(token)
    return words, extensions


def match_files(
    text: str,
    entries: list[FoundFile],
    opened: dict[str, float] | None = None,
    limit: int = 12,
) -> list[FoundFile]:
    """Every file whose name carries all the words, newest first."""
    words, extensions = parse_query(text)
    if not words and not extensions:
        return []
    recent = opened or {}
    matches: list[FoundFile] = []
    for entry in entries:
        lowered = entry.name.lower()
        if extensions and not any(lowered.endswith(ext) for ext in extensions):
            continue
        if not all(_word_in(word, lowered) for word in words):
            continue
        matches.append(
            FoundFile(entry.name, entry.path, entry.modified, recent.get(lowered, 0.0))
        )
    matches.sort(key=lambda row: (row.last_used, row.name), reverse=True)
    return matches[:limit]


def _word_in(word: str, name: str) -> bool:
    """'dragons' still finds dragon-head.stl: a plural falls back to its stem."""
    if word in name:
        return True
    return word.endswith("s") and len(word) > 2 and word[:-1] in name


def when_label(stamp: float, now: datetime | None = None) -> str:
    if stamp <= 0:
        return ""
    try:
        moment = datetime.fromtimestamp(stamp).astimezone()
    except (OverflowError, OSError, ValueError):
        # A nonsense file date from a damaged disk is not worth a crash.
        return ""
    today = (now or datetime.now().astimezone()).date()
    days = (today - moment.date()).days
    if days <= 0:
        return "from today"
    if days == 1:
        return "from yesterday"
    if days < 7:
        return f"from {moment.strftime('%A')}"
    return f"from {moment.strftime('%B %d')}"


def search_reply(
    query: str, matches: list[FoundFile], folders: list[str]
) -> tuple[str, str, FoundFile | None]:
    """(speech, screen text, the one file to open or None)."""
    shown = " ".join((query or "").split())[:80]
    if not matches:
        names = ", ".join(Path(folder).name or folder for folder in folders)
        return (
            f"Nothing matching {shown} in {names}. "
            "Settings can add another folder to search.",
            "Searched: " + "\n".join(folders),
            None,
        )
    if len(matches) == 1:
        best = matches[0]
        label = when_label(best.last_used)
        speech = f"Opening {best.name}" + (f", {label}." if label else ".")
        return speech, best.path, best
    lines = []
    for index, found in enumerate(matches, start=1):
        label = when_label(found.last_used)
        middle = f" — {label}" if label else ""
        lines.append(f"{index}. {found.name}{middle} — {found.path}")
    best = matches[0]
    speech = (
        f"Found {len(matches)} matching {shown}. The newest is {best.name}. "
        f"Say open number 1 to {len(matches)}."
    )
    return speech, "\n".join(lines), None


# Kinds that Windows would run instead of show. The search can list them,
# but speaking a number never starts a program.
NEVER_OPEN = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".msix", ".scr", ".pif",
    ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
    ".hta", ".reg", ".lnk", ".url", ".jar", ".py", ".pyw", ".appx",
}


def open_found(found: FoundFile) -> str:
    """Open one file this search listed, the same way as a double-click.

    A program or a script is never started this way: opening those by
    voice is how a stray match becomes code running on your PC.
    """
    suffix = Path(found.name).suffix.lower()
    if suffix in NEVER_OPEN:
        return (
            f"{found.name} is a program, not a document, so it was not started. "
            "Its place is on the screen if you want it."
        )
    if sys.platform != "win32":
        return "Opening files works on Windows."
    try:
        os.startfile(found.path)  # noqa: S606 — same as a double-click, documents only
    except OSError as exc:
        return f"Windows could not open {found.name} ({exc})."
    return f"Opened {found.name}."
