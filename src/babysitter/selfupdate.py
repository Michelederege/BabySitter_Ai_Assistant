"""Finish an update after the old BabySitter window has closed.

On Windows a running BabySitter.exe locks its own file until the process
and its PyInstaller wrapper exit. The helper started with --finish-update
waits for those processes to leave, moves the freshly built or verified
file into place, and opens BabySitter again with no console window.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import psutil

from babysitter.paths import data_dir
from babysitter.platform import popen_hidden, running_inside_exe
from babysitter.version import __version__


def updates_dir() -> Path:
    path = data_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def repo_hint_path() -> Path:
    return data_dir() / "repo_location.txt"


def remember_repo_path(repo: Path) -> None:
    """Save the BabySitter git folder path so a desktop exe copy can find it."""
    try:
        resolved = str(Path(repo).resolve())
        hint = repo_hint_path()
        if hint.is_file() and hint.read_text(encoding="utf-8").strip() == resolved:
            return
        hint.write_text(resolved + "\n", encoding="utf-8")
    except OSError:
        return


def saved_repo_path() -> Path | None:
    hint = repo_hint_path()
    try:
        if not hint.is_file():
            return None
        raw = hint.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    return Path(raw)


def clean_pyinstaller_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Keep a new BabySitter.exe from inheriting the old process's unpack folder."""
    env = dict(os.environ)
    env.pop("_MEIPASS", None)
    env.pop("_MEIPASS2", None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if extra:
        env.update(extra)
    return env


def current_process_pids() -> list[int]:
    """This Python process, plus PyInstaller's outer exe wrapper when frozen."""
    pid = os.getpid()
    pids = [pid]
    if not running_inside_exe():
        return pids
    try:
        proc = psutil.Process(pid)
        parent = proc.parent()
        if parent is not None and parent.pid and parent.pid != pid:
            own_name = (proc.name() or "").lower()
            parent_name = (parent.name() or "").lower()
            if own_name and parent_name == own_name:
                pids.append(parent.pid)
    except (psutil.Error, OSError):
        pass
    return pids


def write_update_manifest(
    *,
    from_version: str,
    to_version: str,
    relaunch_cmd: list[str],
    relaunch_cwd: str = "",
    relaunch_env: dict[str, str] | None = None,
    staged_exe: str = "",
    targets: list[str] | None = None,
    installer_exe: str = "",
    wait_pids: list[int] | None = None,
) -> Path:
    payload = {
        "wait_pids": list(current_process_pids() if wait_pids is None else wait_pids),
        "from_version": str(from_version or ""),
        "to_version": str(to_version or ""),
        "staged_exe": str(staged_exe or ""),
        "targets": [str(item) for item in (targets or []) if item],
        "installer_exe": str(installer_exe or ""),
        "relaunch_cmd": [str(item) for item in relaunch_cmd if item],
        "relaunch_cwd": str(relaunch_cwd or ""),
        "relaunch_env": dict(relaunch_env or {}),
    }
    manifest = updates_dir() / "pending-update.json"
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest


def spawn_finish_update(
    manifest_path: Path,
    helper_cmd: list[str],
    helper_env: dict[str, str] | None = None,
) -> None:
    args = [*helper_cmd, "--finish-update", str(manifest_path)]
    popen_hidden(
        args,
        cwd=str(updates_dir()),
        env=clean_pyinstaller_env(helper_env),
    )


def _replace_with_retries(source: Path, target: Path, *, sleep_fn=time.sleep) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".updating")
    last_error: OSError | None = None
    for _ in range(60):
        try:
            shutil.copy2(source, part)
            os.replace(part, target)
            return
        except OSError as exc:
            last_error = exc
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
            sleep_fn(0.25)
    if last_error is not None:
        raise last_error


def close_old_copy(pids: list[int]) -> None:
    """End the old BabySitter that did not close by itself.

    Only the process ids the old copy wrote into its own manifest, and only
    when the program is still BabySitter or Python. A reused id that now
    belongs to something else is left alone.
    """
    for pid in pids:
        try:
            proc = psutil.Process(int(pid))
            name = (proc.name() or "").lower()
            if not (name.startswith("babysitter") or name.startswith("python")):
                continue
            proc.terminate()
        except (psutil.Error, OSError, ValueError):
            continue


def run_finish_update(
    manifest_arg: str,
    *,
    sleep_fn=time.sleep,
    pid_exists_fn=psutil.pid_exists,
    popen_fn=popen_hidden,
    close_fn=None,
) -> int:
    """Wait for the closing BabySitter process, swap files, and relaunch."""
    allowed_dir = updates_dir().resolve()
    manifest_path = Path(manifest_arg).resolve()
    if manifest_path.parent != allowed_dir or not manifest_path.is_file():
        return 1
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1

    wait_pids = [
        int(pid)
        for pid in (payload.get("wait_pids") or [])
        if isinstance(pid, int) and pid > 0 and pid != os.getpid()
    ]
    close_fn = close_fn or close_old_copy
    for _ in range(240):
        if not any(pid_exists_fn(pid) for pid in wait_pids):
            break
        sleep_fn(0.25)
    else:
        # A minute is far longer than a normal shutdown. The old copy is
        # stuck, and opening the new one beside it left two windows.
        close_fn(wait_pids)
        for _ in range(20):
            if not any(pid_exists_fn(pid) for pid in wait_pids):
                break
            sleep_fn(0.25)

    staged_raw = str(payload.get("staged_exe") or "").strip()
    targets = [Path(item) for item in (payload.get("targets") or []) if item]
    failed = ""
    if staged_raw and targets:
        staged = Path(staged_raw)
        primary = targets[0]
        if not staged.is_file():
            failed = "The new BabySitter.exe was missing, so the old one was kept."
        else:
            try:
                _replace_with_retries(staged, primary, sleep_fn=sleep_fn)
            except OSError:
                failed = (
                    f"{primary.name} could not be replaced. Another program may have it open. "
                    "The old version was kept. Try the update again."
                )
        if not failed:
            for extra in targets[1:]:
                try:
                    _replace_with_retries(staged, extra, sleep_fn=sleep_fn)
                except OSError:
                    # A secondary copy should not block opening the main exe.
                    pass

    note_path = allowed_dir / "last-update.json"
    note = {
        "from": str(payload.get("from_version") or ""),
        "to": str(payload.get("to_version") or ""),
    }
    if failed:
        note["failed"] = failed
    try:
        note_path.write_text(json.dumps(note), encoding="utf-8")
    except OSError:
        pass

    try:
        manifest_path.unlink(missing_ok=True)
    except OSError:
        pass

    installer_raw = str(payload.get("installer_exe") or "").strip()
    if installer_raw and not failed:
        installer = Path(installer_raw)
        if installer.is_file():
            popen_fn(
                [str(installer), "/SILENT"],
                cwd=str(allowed_dir),
                env=clean_pyinstaller_env(),
            )
            return 0
        return 1

    relaunch_cmd = [str(item) for item in (payload.get("relaunch_cmd") or []) if item]
    if relaunch_cmd:
        relaunch_cwd = str(payload.get("relaunch_cwd") or "").strip() or None
        relaunch_env_raw = payload.get("relaunch_env")
        extra_env = relaunch_env_raw if isinstance(relaunch_env_raw, dict) else None
        popen_fn(
            relaunch_cmd,
            cwd=relaunch_cwd,
            env=clean_pyinstaller_env(extra_env),
        )
    # The old version is opened again either way, so a failed swap never
    # leaves the PC with no BabySitter window and no word about why.
    return 1 if failed else 0


def consume_completed_update(current_version: str = __version__) -> str:
    """Clean temporary update files on launch and return a one-time update note."""
    folder = updates_dir()
    for name in ("BabySitter-new.exe", "BabySitter-new"):
        try:
            (folder / name).unlink(missing_ok=True)
        except OSError:
            pass
    note_path = folder / "last-update.json"
    if not note_path.is_file():
        return ""
    try:
        payload = json.loads(note_path.read_text(encoding="utf-8"))
        note_path.unlink(missing_ok=True)
    except (OSError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    failed = str(payload.get("failed") or "").strip()
    if failed:
        return f"The update did not finish. {failed}"
    old = str(payload.get("from") or "").strip()
    target = str(payload.get("to") or current_version).strip() or current_version
    if old and old != current_version:
        return f"Updated BabySitter from {old} to {current_version}."
    return f"Updated BabySitter to {target}."
