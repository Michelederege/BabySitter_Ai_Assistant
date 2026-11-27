"""The scan's top apps and warning signs. Made-up process lists only."""

import subprocess

from babysitter.pcreport import (
    ProcessRow,
    defender_threats,
    report_detail,
    report_speech,
    suspicious,
    top_apps,
)

GB = 1024 ** 3
MB = 1024 ** 2
ENV = {"WINDIR": r"C:\Windows", "TEMP": r"C:\Users\Me\AppData\Local\Temp"}


def _exists(_path):
    return True


def test_top_apps_group_processes_and_skip_windows():
    rows = [
        ProcessRow("chrome.exe", 10, GB, 3.0),
        ProcessRow("chrome.exe", 11, GB, 2.0),
        ProcessRow("bg3.exe", 12, int(1.5 * GB), 30.0),
        ProcessRow("svchost.exe", 13, 3 * GB, 1.0),
        ProcessRow("MemCompression", 14, 4 * GB, 0.0),
        ProcessRow("Discord.exe", 15, 400 * MB, 1.0),
        ProcessRow("pythonw.exe", 16, 2 * GB, 1.0),
    ]
    apps = top_apps(rows, skip_pids={16})
    assert [(app.name, app.count) for app in apps] == [("chrome", 2), ("bg3", 1), ("Discord", 1)]
    assert apps[0].rss == 2 * GB and apps[0].cpu == 5.0


def test_a_windows_name_outside_windows_is_flagged():
    rows = [
        ProcessRow("svchost.exe", 1, MB, exe=r"C:\Windows\System32\svchost.exe"),
        ProcessRow("svchost.exe", 2, MB, exe=r"C:\Users\Me\AppData\Roaming\svchost.exe"),
    ]
    flags = suspicious(rows, [], env=ENV, exists=_exists)
    assert len(flags) == 1 and "Windows program" in flags[0].reason
    assert "AppData" in flags[0].reason and "Roaming" in flags[0].reason


def test_a_near_miss_on_a_windows_name_is_flagged():
    rows = [
        ProcessRow("svch0st.exe", 1, MB, exe=r"C:\Program Files\x\svch0st.exe"),
        ProcessRow("scvhost.exe", 2, MB, exe=r"C:\Program Files\x\scvhost.exe"),
        ProcessRow("explorar.exe", 3, MB, exe=r"C:\Program Files\x\explorar.exe"),
        ProcessRow("Spotify.exe", 4, MB, exe=r"C:\Program Files\Spotify\Spotify.exe"),
        ProcessRow("dwm.exe", 5, MB, exe=r"C:\Windows\System32\dwm.exe"),
    ]
    names = [flag.name for flag in suspicious(rows, [], env=ENV, exists=_exists)]
    assert names == ["svch0st.exe", "explorar.exe"] or set(names) >= {"svch0st.exe", "explorar.exe"}
    assert "Spotify.exe" not in names and "dwm.exe" not in names


def test_temp_downloads_and_deleted_files_are_flagged():
    rows = [
        ProcessRow("x.exe", 1, MB, exe=r"C:\Users\Me\AppData\Local\Temp\abc\x.exe"),
        ProcessRow("y.exe", 2, MB, exe=r"C:\Users\Me\Downloads\y.exe"),
        ProcessRow("z.exe", 3, MB, exe=r"C:\Program Files\Z\z.exe"),
        ProcessRow("fine.exe", 4, MB, exe=r"C:\Program Files\Fine\fine.exe"),
    ]
    gone = {r"C:\Program Files\Z\z.exe"}
    flags = {flag.name: flag.reason for flag in suspicious(rows, [], env=ENV, exists=lambda p: p not in gone)}
    assert "Temp folder" in flags["x.exe"]
    assert "Downloads" in flags["y.exe"]
    assert "deleted" in flags["z.exe"]
    assert "fine.exe" not in flags


def test_startup_entries_that_hide_what_they_run_are_flagged():
    startups = [
        ("Updater", "powershell.exe -w hidden -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA"),
        ("Helper", r"wscript.exe C:\Users\Me\AppData\Roaming\h.vbs"),
        ("Dropper", r'"C:\Users\Me\AppData\Local\Temp\d.exe" /silent'),
        ("Spotify", r'"C:\Users\Me\AppData\Roaming\Spotify\Spotify.exe" /minimized'),
    ]
    flags = {flag.name: flag.reason for flag in suspicious([], startups, env=ENV, exists=_exists)}
    assert "PowerShell" in flags["Updater"]
    assert "script" in flags["Helper"]
    assert "Temp" in flags["Dropper"]
    assert "Spotify" not in flags


def test_babysitter_itself_is_never_flagged():
    rows = [ProcessRow("pythonw.exe", 99, MB, exe=r"C:\Users\Me\Downloads\BabySitter\.venv\Scripts\pythonw.exe")]
    assert suspicious(rows, [], env=ENV, exists=_exists, skip_pids={99}) == []


def test_defender_lines_and_unreadable_defender(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")

    def ran(stdout, code=0):
        return lambda args, timeout=0: subprocess.CompletedProcess(args, code, stdout=stdout, stderr="")

    found = defender_threats(run=ran('{"ThreatName":"Trojan:Win32/Wacatac","IsActive":true,"Paths":"file:_C:/x.exe"}'))
    assert found == ["Trojan:Win32/Wacatac, still active, at file:_C:/x.exe"]
    assert defender_threats(run=ran("")) == []
    assert defender_threats(run=ran("", code=1)) is None


def test_the_spoken_report_is_short_and_the_detail_is_complete():
    apps = top_apps([ProcessRow("chrome.exe", 1, 2 * GB, 5.0), ProcessRow("bg3.exe", 2, GB, 30.0)])
    flags = suspicious([ProcessRow("x.exe", 3, MB, exe=r"C:\Users\Me\Downloads\x.exe")], [], env=ENV, exists=_exists)
    said = report_speech(apps, flags, [])
    assert said.startswith("Your top apps by memory are chrome at 2.0 GB, and bg3 at 1.0 GB.")
    assert "1 thing looks suspicious: x.exe" in said
    detail = report_detail(apps, flags, None)
    assert "1. chrome — 2.0 GB, 5% processor" in detail
    assert "could not be read" in detail
    clean = report_speech(apps, [], [])
    assert "Nothing looks suspicious, and Defender has no recent detections." in clean


def test_windows_pseudo_processes_and_honest_helpers_are_not_flagged():
    rows = [
        ProcessRow("Registry", 1, MB, exe="Registry"),
        ProcessRow("MemCompression", 2, MB, exe="MemCompression"),
        ProcessRow("service.exe", 3, MB, exe=r"C:\Program Files\NZXT CAM\service.exe"),
        ProcessRow("servicess.exe", 4, MB, exe=r"C:\Program Files\X\servicess.exe"),
    ]
    # The pseudo processes have no file at all; the two helpers' files are there.
    assert suspicious(rows, [], env=ENV, exists=lambda path: "Program Files" in path) == []
