"""What "scan my PC" reports: the top apps, and anything that looks wrong.

Everything here only reads. A flag is a reason to look closer, never an
action: nothing is closed, deleted, or quarantined because of one. Each
flag says why it was raised, in a plain sentence. Windows Defender's own
recent detections are read too, when Windows lets this user read them.

This is not a virus scanner. It catches the common tells: a program named
like a Windows file but running from somewhere else, a near miss on such a
name, a program running from Temp or Downloads, a program whose file was
deleted while it runs, and a startup entry that hides what it starts.
"""

from __future__ import annotations

import json
import ntpath  # process paths are Windows paths, read the same way on any computer (CI runs Linux)
import os
import re
from dataclasses import dataclass

# Windows' own programs. Anything else using one of these names, or a
# near miss on one, is the oldest disguise there is.
SYSTEM_NAMES = {
    "svchost", "lsass", "csrss", "winlogon", "services", "smss", "wininit",
    "dwm", "taskhostw", "conhost", "rundll32", "spoolsv", "explorer",
    "ctfmon", "sihost", "fontdrvhost", "dllhost", "runtimebroker",
    "searchindexer", "taskmgr", "regsvr32", "lsaiso",
}

# Grouped away from the top list: they are Windows, not apps.
NOT_AN_APP = SYSTEM_NAMES | {
    "system", "idle", "system idle process", "registry", "memory compression",
    "memcompression", "secure system", "msmpeng", "audiodg", "searchhost",
    "startmenuexperiencehost", "textinputhost", "shellexperiencehost",
    "applicationframehost", "securityhealthservice", "nissrv", "wmiprvse",
    "msedgewebview2", "widgets", "phoneexperiencehost", "lockapp",
}


@dataclass(frozen=True)
class ProcessRow:
    name: str
    pid: int
    rss: int
    cpu: float = 0.0  # percent of the whole processor
    exe: str = ""  # empty when Windows would not say


@dataclass(frozen=True)
class AppUse:
    name: str
    rss: int
    cpu: float
    count: int


@dataclass(frozen=True)
class Flag:
    name: str
    where: str
    reason: str


def _stem(name: str) -> str:
    base = (name or "").strip().lower()
    return base[:-4] if base.endswith(".exe") else base


def _folder(path: str) -> str:
    return ntpath.dirname((path or "").replace("/", "\\")).rstrip("\\").lower()


def top_apps(rows: list[ProcessRow], n: int = 5, skip_pids: set[int] | None = None) -> list[AppUse]:
    """The heaviest apps by memory. Chrome's thirty processes count as one Chrome."""
    skip = skip_pids or set()
    grouped: dict[str, list[ProcessRow]] = {}
    shown: dict[str, str] = {}
    for row in rows:
        stem = _stem(row.name)
        if not stem or stem in NOT_AN_APP or row.pid in skip:
            continue
        grouped.setdefault(stem, []).append(row)
        shown.setdefault(stem, row.name[:-4] if row.name.lower().endswith(".exe") else row.name)
    apps = [
        AppUse(
            name=shown[stem],
            rss=sum(max(0, r.rss) for r in group),
            cpu=sum(max(0.0, r.cpu) for r in group),
            count=len(group),
        )
        for stem, group in grouped.items()
    ]
    apps.sort(key=lambda app: (app.rss, app.cpu), reverse=True)
    return apps[:n]


def _near_miss(stem: str) -> str | None:
    """The Windows name this one imitates, when it is one letter off."""
    if stem in SYSTEM_NAMES or len(stem) < 6:
        return None
    swapped = stem.translate(str.maketrans("0135", "oles"))
    for real in SYSTEM_NAMES:
        if len(real) < 6:
            continue
        if swapped == real or _one_edit(stem, real):
            return real
    return None


def _one_edit(a: str, b: str) -> bool:
    """One letter swapped for another, or two neighbours switched round.

    A letter added or dropped is left out: "service" for NZXT CAM and many
    other honest helpers sit one letter from a Windows name that way.
    """
    if a == b or len(a) != len(b):
        return False
    differ = [index for index, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(differ) == 1:
        return True
    if len(differ) == 2 and differ[1] == differ[0] + 1:
        i, j = differ
        return a[i] == b[j] and a[j] == b[i]
    return False


def _risky_place(path: str, env: dict[str, str]) -> str | None:
    lowered = (path or "").replace("/", "\\").lower()
    if not lowered:
        return None
    temp = (env.get("TEMP") or "").replace("/", "\\").lower().rstrip("\\")
    if (temp and lowered.startswith(temp + "\\")) or "\\appdata\\local\\temp\\" in lowered:
        return "your Temp folder"
    if "\\$recycle.bin\\" in lowered:
        return "the Recycle Bin"
    if "\\downloads\\" in lowered:
        return "your Downloads folder"
    if lowered.startswith("c:\\users\\public\\"):
        return "the Public user folder"
    return None


def suspicious(
    rows: list[ProcessRow],
    startups: list[tuple[str, str]],
    *,
    env: dict[str, str] | None = None,
    exists=os.path.exists,
    skip_pids: set[int] | None = None,
) -> list[Flag]:
    """Plain reasons to look closer. One flag per program name."""
    env = dict(os.environ if env is None else env)
    windir = (env.get("WINDIR") or env.get("SystemRoot") or r"C:\Windows").replace("/", "\\").lower().rstrip("\\")
    allowed = {windir, windir + "\\system32", windir + "\\syswow64", windir + "\\systemapps"}
    skip = skip_pids or set()
    flags: list[Flag] = []
    seen: set[str] = set()

    def add(name: str, where: str, reason: str) -> None:
        key = f"{_stem(name)}|{reason}"
        if key not in seen:
            seen.add(key)
            flags.append(Flag(name, where, reason))

    for row in rows:
        if row.pid in skip or not row.name:
            continue
        stem = _stem(row.name)
        folder = _folder(row.exe)
        if stem in SYSTEM_NAMES and row.exe and folder not in allowed:
            shown = ntpath.dirname(row.exe.replace("/", "\\"))
            add(row.name, row.exe, f"It has the name of a Windows program, but it runs from {shown}, not from Windows' own folder.")
            continue
        imitated = _near_miss(stem)
        if imitated:
            add(row.name, row.exe or "unknown place", f"Its name is one letter off Windows' {imitated}.exe.")
            continue
        place = _risky_place(row.exe, env)
        if place:
            add(row.name, row.exe, f"It runs from {place}. Installers do that while they run; anything else there is worth a look.")
            continue
        # Only a real path. Windows' own Registry and MemCompression report
        # a bare name, because they have no file at all.
        if ntpath.isabs(row.exe) and ("\\" in row.exe or "/" in row.exe) and not exists(row.exe):
            add(row.name, row.exe, "Its file was deleted while it kept running.")

    for name, command in startups:
        lowered = (command or "").lower()
        place = _risky_place(lowered.strip('"').split('"')[0] if lowered.startswith('"') else lowered.split(" ")[0], env)
        hidden = bool(re.search(r"powershell[^\n]*(-enc\b|-encodedcommand|-e\s+[a-z0-9+/=]{20,}|-w(indowstyle)?\s+hidden)", lowered))
        script = bool(re.search(r"\b(wscript|cscript|mshta)(\.exe)?\b[^\n]*\\appdata\\", lowered))
        if hidden:
            add(name, command[:160], "It starts with Windows and runs hidden or encoded PowerShell.")
        elif script:
            add(name, command[:160], "It starts with Windows and runs a script from your AppData folder.")
        elif place:
            add(name, command[:160], f"It starts with Windows from {place}.")
    return flags


DEFENDER_SCRIPT = (
    "$ErrorActionPreference='Stop'; "
    "Get-MpThreat | Select-Object -First 5 ThreatName, IsActive, "
    "@{n='Paths';e={($_.Resources | Select-Object -First 2) -join '; '}} | ConvertTo-Json -Compress"
)


def defender_threats(run=None) -> list[str] | None:
    """Windows Defender's own recent finds, as short lines. None when it cannot be read."""
    import sys

    if sys.platform != "win32":
        return None
    if run is None:
        from babysitter.platform import run_hidden as run
    try:
        done = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", DEFENDER_SCRIPT], timeout=20)
    except Exception:
        return None
    if done.returncode != 0:
        return None
    text = (done.stdout or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return None
    items = data if isinstance(data, list) else [data]
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("ThreatName") or "Unknown threat")
        state = "still active" if item.get("IsActive") else "handled"
        where = str(item.get("Paths") or "")
        lines.append(f"{name}, {state}" + (f", at {where[:140]}" if where else ""))
    return lines


def collect_rows(sample_seconds: float = 1.0, watch_apps: int = 8) -> list[ProcessRow]:
    """Every process with its memory and its file, and the processor share
    of the heaviest apps.

    Each reading of a process costs Windows a few milliseconds, and a PC
    runs hundreds of them. Memory and files are read once for all of them.
    The second processor reading, a second later, covers only the
    processes of the heaviest apps, which are the ones that are spoken.
    """
    import time

    import psutil

    first: dict[int, tuple[psutil.Process, float]] = {}
    rows: list[ProcessRow] = []
    started = time.monotonic()
    for proc in psutil.process_iter(["name", "pid", "memory_info", "exe", "cpu_times"]):
        try:
            info = proc.info
            memory = info.get("memory_info")
            times = info.get("cpu_times")
            pid = int(info.get("pid") or 0)
            if times is not None:
                first[pid] = (proc, float(times.user + times.system))
            rows.append(
                ProcessRow(
                    name=str(info.get("name") or ""),
                    pid=pid,
                    rss=int(getattr(memory, "rss", 0) or 0),
                    exe=str(info.get("exe") or ""),
                )
            )
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    heavy = {_stem(app.name) for app in top_apps(rows, n=watch_apps)}
    watched = [row for row in rows if _stem(row.name) in heavy and row.pid in first]
    time.sleep(max(0.0, sample_seconds - (time.monotonic() - started)))
    elapsed = max(0.001, time.monotonic() - started)
    cores = psutil.cpu_count() or 1
    shares: dict[int, float] = {}
    for row in watched:
        proc, before = first[row.pid]
        try:
            times = proc.cpu_times()
        except (psutil.Error, OSError):
            continue
        used = max(0.0, float(times.user + times.system) - before)
        shares[row.pid] = 100.0 * used / (elapsed * cores)
    return [
        ProcessRow(row.name, row.pid, row.rss, shares.get(row.pid, 0.0), row.exe) for row in rows
    ]


def _size(rss: int) -> str:
    gigabytes = rss / (1024 ** 3)
    if gigabytes >= 1:
        return f"{gigabytes:.1f} GB"
    return f"{round(rss / (1024 ** 2)):,} MB"


def report_speech(apps: list[AppUse], flags: list[Flag], threats: list[str] | None) -> str:
    """What is said. The details go on the Health page."""
    parts: list[str] = []
    if apps:
        listed = [f"{app.name} at {_size(app.rss)}" for app in apps]
        joined = ", ".join(listed[:-1]) + f", and {listed[-1]}" if len(listed) > 1 else listed[0]
        parts.append(f"Your top apps by memory are {joined}.")
    if threats:
        active = [line for line in threats if "still active" in line]
        if active:
            parts.append(f"Windows Defender has {len(active)} active threat{'s' if len(active) > 1 else ''}. Open Windows Security now.")
        else:
            parts.append("Windows Defender found something recently and has handled it.")
    if flags:
        count = len(flags)
        names = ", ".join(flag.name for flag in flags[:3])
        parts.append(
            f"{count} thing{'s' if count > 1 else ''} look{'' if count > 1 else 's'} suspicious: {names}. "
            "The reasons are on the Health page. I didn't touch them."
        )
    elif threats is not None and not threats:
        parts.append("Nothing looks suspicious, and Defender has no recent detections.")
    else:
        parts.append("Nothing looks suspicious.")
    return " ".join(parts)


def report_detail(apps: list[AppUse], flags: list[Flag], threats: list[str] | None) -> str:
    lines = ["Top apps by memory:"]
    for index, app in enumerate(apps, start=1):
        many = f", {app.count} processes" if app.count > 1 else ""
        lines.append(f"{index}. {app.name} — {_size(app.rss)}, {app.cpu:.0f}% processor{many}")
    lines.append("")
    if flags:
        lines.append("Worth a closer look (nothing was changed):")
        for flag in flags:
            lines.append(f"• {flag.name} — {flag.reason}")
            lines.append(f"  {flag.where}")
    else:
        lines.append("Nothing looks suspicious.")
    lines.append("")
    if threats is None:
        lines.append("Windows Defender's history could not be read from this account.")
    elif threats:
        lines.append("Windows Defender recently found:")
        lines.extend(f"• {line}" for line in threats)
    else:
        lines.append("Windows Defender has no recent detections.")
    lines.append("")
    lines.append("These are warning signs, not a virus scan. Read only. Nothing left this PC.")
    return "\n".join(lines)
