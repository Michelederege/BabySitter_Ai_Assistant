"""Check for updates and install them from inside BabySitter after you confirm.

When your BabySitter git folder is on this PC, updates come straight from
Origin main so you never have to run git push or git pull in PowerShell.
When BabySitter is installed on a PC without a git folder, it checks GitHub
Releases and verifies the SHA-256 fingerprint before replacing anything.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from babysitter.paths import asset_path, project_root
from babysitter.platform import run_hidden, running_inside_exe
from babysitter.security import (
    normalize_sha256,
    require_release_asset_url,
    require_sha256_file,
    require_update_url,
)
from babysitter.selfupdate import (
    clean_pyinstaller_env,
    remember_repo_path,
    saved_repo_path,
    updates_dir,
    write_update_manifest,
)
from babysitter.version import __version__


RELEASE_API = "https://api.github.com/repos/Michelederege/BabySitter_Ai_Assistant/releases/latest"
_MAX_RELEASE_BYTES = 450 * 1024 * 1024
_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


class UpdateError(Exception):
    """Checking or applying an update did not finish."""


@dataclass(frozen=True)
class UpdatePlan:
    available: bool
    source: str
    current_version: str
    target_version: str
    commits_behind: int = 0
    headlines: tuple[str, ...] = ()
    summary: str = ""
    confirm_body: str = ""
    repo_path: str = ""
    target_commit: str = ""
    asset_url: str = ""
    asset_name: str = ""
    asset_sha256: str = ""
    asset_kind: str = ""
    needs_exe_rebuild: bool = False
    dirty_files: tuple[str, ...] = ()
    can_install: bool = False


@dataclass(frozen=True)
class PreparedUpdate:
    message: str
    manifest_path: Path
    helper_cmd: list[str]
    helper_env: dict[str, str]


def _numbers(text: str) -> tuple[int, ...]:
    digits = []
    for part in (text or "").lstrip("vV").split("."):
        number = ""
        for character in part:
            if character.isdigit():
                number += character
            else:
                break
        if number:
            digits.append(int(number))
    return tuple(digits) or (0,)


def is_newer(remote: str, current: str = __version__) -> bool:
    left = _numbers(remote)
    right = _numbers(current)
    width = max(len(left), len(right))
    left = left + (0,) * (width - len(left))
    right = right + (0,) * (width - len(right))
    return left > right


def parse_version_text(text: str) -> str:
    match = _VERSION_RE.search(text or "")
    return match.group(1).strip() if match else ""


def describe_release(payload: dict, current: str = __version__) -> str:
    if not isinstance(payload, dict):
        raise UpdateError("GitHub did not return a release.")
    tag = str(payload.get("tag_name") or "").strip()
    page = str(payload.get("html_url") or "")
    if not tag:
        return "No published release yet. Nothing was downloaded."
    if is_newer(tag, current):
        parsed = urllib.parse.urlsplit(page)
        owned = (
            (parsed.hostname or "") == "github.com"
            and "Michelederege/BabySitter_Ai_Assistant" in (parsed.path or "")
        )
        where = f" The page is {page}." if parsed.scheme == "https" and owned else ""
        return (
            f"Version {tag} is published. You are on {current}. "
            "BabySitter did not download it, and it does not sign the installer."
            + where
        )
    return f"You are on {current}, and {tag} is not newer. Nothing was downloaded."


def _fetch_release_payload(opener=None) -> dict:
    require_update_url(RELEASE_API)
    request = urllib.request.Request(
        RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "BabySitter"},
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=10) as response:
            raw = response.read(250_000)
    except Exception as exc:
        raise UpdateError("GitHub did not answer. Nothing was downloaded.") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError("GitHub sent something BabySitter could not read.") from exc
    if not isinstance(payload, dict):
        raise UpdateError("GitHub did not return a release.")
    return payload


def check_latest(opener=None, current: str = __version__) -> str:
    payload = _fetch_release_payload(opener=opener)
    return describe_release(payload, current)


def _is_babysitter_repo(folder: Path | None) -> bool:
    if folder is None:
        return False
    try:
        return (
            (folder / ".git").exists()
            and (folder / "packaging" / "babysitter.spec").is_file()
            and (folder / "src" / "babysitter" / "version.py").is_file()
        )
    except OSError:
        return False


def find_git_repo(explicit: Path | None = None) -> Path | None:
    """Locate the local BabySitter git checkout when present on this PC."""
    override = os.environ.get("BABYSITTER_REPO_DIR")
    if override is not None:
        cleaned = override.strip()
        if not cleaned or cleaned.lower() == "none":
            return None
        candidate = Path(cleaned)
        if _is_babysitter_repo(candidate):
            resolved = candidate.resolve()
            remember_repo_path(resolved)
            return resolved
        return None

    exe_path = Path(sys.executable).resolve()
    candidates: list[Path | None] = [
        explicit,
        project_root(),
        exe_path.parent,
        exe_path.parent.parent,
        saved_repo_path(),
        Path.cwd(),
    ]
    if sys.platform == "win32":
        candidates.append(Path(r"C:\BabySitter"))
    candidates.append(Path.home() / "BabySitter")

    seen: set[str] = set()
    for item in candidates:
        if item is None:
            continue
        try:
            resolved = item.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if _is_babysitter_repo(resolved):
            remember_repo_path(resolved)
            return resolved
    return None


def bundled_git_commit() -> str:
    """Commit hash packed into BabySitter.exe at build time, if recorded."""
    path = asset_path("git-commit.txt")
    try:
        if not path.is_file():
            return ""
        raw = path.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return ""
    if len(raw) == 40 and all(ch in "0123456789abcdef" for ch in raw):
        return raw
    return ""


def _git_text(repo: Path, args: list[str], *, run_cmd=run_hidden, timeout: float = 15) -> str:
    try:
        done = run_cmd(["git", "-C", str(repo), *args], timeout=timeout)
    except FileNotFoundError as exc:
        raise UpdateError("Git is not installed on this PC.") from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateError("Git took too long to answer. Check your connection and try again.") from exc
    except OSError as exc:
        raise UpdateError(f"Could not run git ({exc}).") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        first = detail[0] if detail else "git returned an error"
        raise UpdateError(f"Git could not finish ({first}).")
    return (done.stdout or "").strip()


def _dirty_tracked_files(repo: Path, *, run_cmd=run_hidden) -> tuple[str, ...]:
    done = run_cmd(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
        timeout=15,
    )
    if done.returncode != 0:
        raise UpdateError("Git could not check local changes.")
    files: list[str] = []
    for raw_line in (done.stdout or "").splitlines():
        if not raw_line.strip():
            continue
        entry = raw_line[3:].strip() if len(raw_line) > 3 else raw_line.strip()
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1].strip()
        if entry:
            files.append(entry)
    return tuple(files)


def _check_git_repo(
    repo: Path,
    *,
    current: str,
    is_frozen: bool,
    built_commit: str = "",
    run_cmd=run_hidden,
) -> UpdatePlan:
    try:
        _git_text(repo, ["fetch", "origin", "main"], run_cmd=run_cmd, timeout=25)
    except UpdateError as exc:
        raise UpdateError(
            f"Could not reach Origin main from {repo}. Make sure this PC is online. ({exc})"
        ) from exc

    origin_sha = _git_text(repo, ["rev-parse", "origin/main"], run_cmd=run_cmd)
    behind_raw = _git_text(repo, ["rev-list", "--count", "HEAD..origin/main"], run_cmd=run_cmd)
    behind = int(behind_raw or "0")
    try:
        remote_ver_file = _git_text(
            repo,
            ["show", "origin/main:src/babysitter/version.py"],
            run_cmd=run_cmd,
        )
    except UpdateError:
        remote_ver_file = ""
    remote_version = parse_version_text(remote_ver_file) or current
    dirty = _dirty_tracked_files(repo, run_cmd=run_cmd)

    base_ref = "HEAD"
    exe_behind = behind
    if is_frozen:
        packed_sha = built_commit or bundled_git_commit()
        if packed_sha:
            if packed_sha == origin_sha:
                outdated = False
                exe_behind = 0
            else:
                try:
                    count_raw = _git_text(
                        repo,
                        ["rev-list", "--count", f"{packed_sha}..origin/main"],
                        run_cmd=run_cmd,
                    )
                    exe_behind = int(count_raw or "0")
                    base_ref = packed_sha
                    outdated = exe_behind > 0 or is_newer(remote_version, current)
                except UpdateError:
                    outdated = behind > 0 or is_newer(remote_version, current)
        else:
            outdated = behind > 0 or is_newer(remote_version, current)
            if not outdated:
                try:
                    ts_raw = _git_text(
                        repo,
                        ["show", "-s", "--format=%ct", "origin/main"],
                        run_cmd=run_cmd,
                    )
                    exe_mtime = int(Path(sys.executable).stat().st_mtime)
                    if int(ts_raw or "0") > exe_mtime + 5:
                        outdated = True
                        exe_behind = max(behind, 1)
                except (UpdateError, OSError, ValueError):
                    pass
    else:
        outdated = behind > 0 or is_newer(remote_version, current)

    if not outdated:
        return UpdatePlan(
            available=False,
            source="git",
            current_version=current,
            target_version=remote_version,
            repo_path=str(repo),
            target_commit=origin_sha,
            summary=f"BabySitter {current} is already up to date with Origin main. Nothing was changed.",
        )

    headlines: list[str] = []
    try:
        log_raw = _git_text(
            repo,
            ["log", "--format=%s", "-n", "5", f"{base_ref}..origin/main"],
            run_cmd=run_cmd,
        )
        headlines = [line.strip() for line in log_raw.splitlines() if line.strip()]
    except UpdateError:
        headlines = []
    if not headlines:
        try:
            top = _git_text(repo, ["log", "-n", "1", "--format=%s", "origin/main"], run_cmd=run_cmd)
            if top:
                headlines = [top]
        except UpdateError:
            pass

    change_count = max(exe_behind, len(headlines), 1)
    needs_rebuild = bool(is_frozen or (repo / "dist" / "BabySitter.exe").is_file())
    if dirty:
        shown = ", ".join(dirty[:3])
        more = f" (+{len(dirty) - 3} more)" if len(dirty) > 3 else ""
        return UpdatePlan(
            available=True,
            source="git",
            current_version=current,
            target_version=remote_version,
            commits_behind=change_count,
            headlines=tuple(headlines),
            repo_path=str(repo),
            target_commit=origin_sha,
            needs_exe_rebuild=needs_rebuild,
            dirty_files=dirty,
            can_install=False,
            summary=(
                f"Origin main has {remote_version} ready, and your folder has unsaved edits in "
                f"{shown}{more}. Save or revert those edits first so BabySitter does not overwrite them."
            ),
        )

    label = "1 new update" if change_count == 1 else f"{change_count} new updates"
    rebuild_line = (
        " BabySitter.exe will also be rebuilt so your desktop shortcut opens the new version."
        if needs_rebuild
        else ""
    )
    bullets = "\n".join(f"- {item}" for item in headlines[:5])
    changes_section = f"Changes waiting on Origin main:\n{bullets}\n\n" if bullets else ""
    return UpdatePlan(
        available=True,
        source="git",
        current_version=current,
        target_version=remote_version,
        commits_behind=change_count,
        headlines=tuple(headlines),
        repo_path=str(repo),
        target_commit=origin_sha,
        needs_exe_rebuild=needs_rebuild,
        can_install=True,
        summary=(
            f"Origin main has {label} ready (version {remote_version}; you are on {current}). "
            "Click Update BabySitter to install and restart. Nothing was changed yet."
        ),
        confirm_body=(
            f"Pull {label} from Origin main into {repo} and update to {remote_version}?{rebuild_line}\n\n"
            f"{changes_section}"
            "Your settings, memories, notes, and saved keys stay untouched."
        ),
    )


def _parse_checksums_asset(assets: list[dict], opener=None) -> dict[str, str]:
    open_url = opener or urllib.request.urlopen
    for asset in assets:
        name = str(asset.get("name") or "").strip()
        if name.lower() not in {"sha256sums.txt", "sha256sum.txt", "checksums.txt"}:
            continue
        url = str(asset.get("browser_download_url") or "").strip()
        try:
            require_release_asset_url(url)
            req = urllib.request.Request(url, headers={"User-Agent": "BabySitter"})
            with open_url(req, timeout=10) as resp:
                text = resp.read(64_000).decode("utf-8", errors="replace")
        except Exception:
            return {}
        found: dict[str, str] = {}
        for line in text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                digest = normalize_sha256(parts[0])
                fname = parts[-1].lstrip("*./\\")
                if digest and fname:
                    found[fname.lower()] = digest
        return found
    return {}


def _select_release_asset(payload: dict, *, prefer_installer: bool, opener=None) -> tuple[str, str, str, str]:
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return "", "", "", ""
    checksums: dict[str, str] | None = None
    portable: tuple[str, str, str, str] | None = None
    installer: tuple[str, str, str, str] | None = None

    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or "").strip()
        lower = name.lower()
        if not lower.endswith(".exe"):
            continue
        try:
            require_release_asset_url(url)
        except ValueError:
            continue
        digest = normalize_sha256(str(item.get("digest") or ""))
        if not digest:
            if checksums is None:
                checksums = _parse_checksums_asset(assets, opener=opener)
            digest = checksums.get(lower, "")
        if not digest:
            continue
        if "setup" in lower or "install" in lower:
            installer = (name, url, digest, "installer")
        elif lower == "babysitter.exe" or portable is None:
            portable = (name, url, digest, "portable")

    ordered = (installer, portable) if prefer_installer else (portable, installer)
    for choice in ordered:
        if choice is not None:
            return choice
    return "", "", "", ""


def _check_github_release(
    *,
    current: str,
    is_frozen: bool,
    opener=None,
) -> UpdatePlan:
    payload = _fetch_release_payload(opener=opener)
    speech = describe_release(payload, current)
    tag = str(payload.get("tag_name") or "").strip()
    if not tag or not is_newer(tag, current):
        return UpdatePlan(
            available=False,
            source="github",
            current_version=current,
            target_version=tag or current,
            summary=speech,
        )

    exe_dir = Path(sys.executable).resolve().parent
    prefer_installer = (exe_dir / "unins000.exe").is_file()
    name, url, digest, kind = _select_release_asset(
        payload,
        prefer_installer=prefer_installer,
        opener=opener,
    )
    can_install = bool(
        name
        and url
        and digest
        and (kind == "installer" or is_frozen)
        and (sys.platform == "win32" or opener is not None)
    )
    if not can_install:
        return UpdatePlan(
            available=True,
            source="github",
            current_version=current,
            target_version=tag,
            summary=speech,
            can_install=False,
        )

    return UpdatePlan(
        available=True,
        source="github",
        current_version=current,
        target_version=tag,
        asset_url=url,
        asset_name=name,
        asset_sha256=digest,
        asset_kind=kind,
        can_install=True,
        summary=(
            f"Version {tag} is ready on GitHub (you are on {current}). "
            "BabySitter did not download it yet. "
            "Click Update BabySitter to download it and check its SHA-256 fingerprint"
            + (" and its code signature" if kind == "installer" else "")
            + ", then restart."
        ),
        confirm_body=(
            f"Download {name} ({tag}) from GitHub, check its SHA-256 fingerprint, and restart BabySitter?\n\n"
            + (
                "An installer must also carry a valid code signature, or it is not run. "
                if kind == "installer"
                else "The portable exe is checked by its SHA-256 fingerprint. "
            )
            + "Your settings, memories, notes, and saved keys stay untouched."
        ),
    )


def check_for_update(
    *,
    current: str = __version__,
    repo: Path | None = None,
    opener=None,
    frozen: bool | None = None,
    built_commit: str = "",
    run_cmd=run_hidden,
) -> UpdatePlan:
    """Check Origin main when the git repo is on this PC, else GitHub Releases."""
    is_frozen = running_inside_exe() if frozen is None else frozen
    found_repo = find_git_repo(repo)
    if found_repo is not None:
        return _check_git_repo(
            found_repo,
            current=current,
            is_frozen=is_frozen,
            built_commit=built_commit,
            run_cmd=run_cmd,
        )
    return _check_github_release(current=current, is_frozen=is_frozen, opener=opener)


def _venv_python(repo: Path, *, is_frozen: bool, run_cmd=run_hidden) -> Path | None:
    win_py = repo / ".venv" / "Scripts" / "python.exe"
    posix_py = repo / ".venv" / "bin" / "python"
    for candidate in (win_py, posix_py):
        if candidate.is_file():
            return candidate
    if not is_frozen:
        return Path(sys.executable).resolve()
    if sys.platform == "win32":
        done = run_cmd(
            ["py", "-3.12", "-m", "venv", str(repo / ".venv")],
            timeout=120,
            cwd=repo,
        )
        if done.returncode == 0 and win_py.is_file():
            return win_py
    return None


def _python_has_module(python_exe: Path, module: str, *, run_cmd=run_hidden) -> bool:
    try:
        done = run_cmd([str(python_exe), "-c", f"import {module}"], timeout=20)
    except OSError:
        return False
    return done.returncode == 0


def _prepare_git_update(
    plan: UpdatePlan,
    *,
    is_frozen: bool,
    on_step,
    run_cmd=run_hidden,
) -> PreparedUpdate:
    repo = Path(plan.repo_path).resolve()
    if not _is_babysitter_repo(repo):
        raise UpdateError("Could not find the BabySitter project folder on this PC.")

    on_step("Checking local files…")
    dirty = _dirty_tracked_files(repo, run_cmd=run_cmd)
    if dirty:
        raise UpdateError(
            f"Your project folder has unsaved edits in {', '.join(dirty[:3])}. "
            "Nothing was overwritten."
        )

    old_head = _git_text(repo, ["rev-parse", "HEAD"], run_cmd=run_cmd)
    on_step("Fetching latest changes from Origin main…")
    _git_text(repo, ["fetch", "origin", "main"], run_cmd=run_cmd, timeout=30)

    branch = _git_text(repo, ["rev-parse", "--abbrev-ref", "HEAD"], run_cmd=run_cmd)
    if branch != "main":
        on_step("Switching project folder to main…")
        _git_text(repo, ["checkout", "main"], run_cmd=run_cmd, timeout=20)

    on_step("Applying latest commits from Origin main…")
    try:
        _git_text(repo, ["merge", "--ff-only", "origin/main"], run_cmd=run_cmd, timeout=30)
    except UpdateError:
        # Put the folder back on the branch it was on, so a failed update
        # does not leave someone's work switched away underneath them.
        if branch not in {"main", "HEAD", ""}:
            try:
                _git_text(repo, ["checkout", branch], run_cmd=run_cmd, timeout=20)
            except UpdateError:
                pass
        raise
    new_head = _git_text(repo, ["rev-parse", "HEAD"], run_cmd=run_cmd)

    version_file = repo / "src" / "babysitter" / "version.py"
    new_version = (
        parse_version_text(version_file.read_text(encoding="utf-8"))
        if version_file.is_file()
        else plan.target_version
    ) or plan.target_version

    changed_files: set[str] = set()
    if old_head != new_head:
        diff_raw = _git_text(
            repo,
            ["diff", "--name-only", old_head, new_head],
            run_cmd=run_cmd,
        )
        changed_files = {line.strip() for line in diff_raw.splitlines() if line.strip()}

    py_exe = _venv_python(repo, is_frozen=is_frozen, run_cmd=run_cmd)
    if py_exe is None:
        if is_frozen:
            raise UpdateError(
                "Updated the code folder, and Python 3.12 (.venv) was not found to rebuild BabySitter.exe."
            )
    else:
        if "requirements.txt" in changed_files:
            on_step("Updating Python libraries…")
            pip_run = run_cmd(
                [str(py_exe), "-m", "pip", "install", "-r", str(repo / "requirements.txt")],
                timeout=300,
                cwd=repo,
                env=clean_pyinstaller_env(),
            )
            if pip_run.returncode != 0:
                raise UpdateError("Could not update requirements.txt libraries.")

    staged_exe_str = ""
    dist_exe = (repo / "dist" / ("BabySitter.exe" if sys.platform == "win32" else "BabySitter")).resolve()
    # Asked once. Each ask starts a Python process and imports PyInstaller.
    has_pyinstaller = py_exe is not None and _python_has_module(py_exe, "PyInstaller", run_cmd=run_cmd)
    should_rebuild = is_frozen or (dist_exe.is_file() and has_pyinstaller)

    if should_rebuild:
        if py_exe is None:
            raise UpdateError("Python 3.12 (.venv) is needed to rebuild BabySitter.exe.")
        if not has_pyinstaller or (
            {"requirements-dev.txt", "requirements-voice.txt"} & changed_files
        ):
            on_step("Checking build and voice libraries…")
            for req_name in ("requirements-dev.txt", "requirements-voice.txt"):
                req_path = repo / req_name
                if req_path.is_file():
                    done = run_cmd(
                        [str(py_exe), "-m", "pip", "install", "-r", str(req_path)],
                        timeout=600,
                        cwd=repo,
                        env=clean_pyinstaller_env(),
                    )
                    if done.returncode != 0 and req_name == "requirements-dev.txt":
                        raise UpdateError("Could not install PyInstaller to rebuild BabySitter.exe.")

        on_step("Rebuilding BabySitter.exe (this takes about a minute)…")
        stage_root = updates_dir() / "staging"
        shutil.rmtree(stage_root, ignore_errors=True)
        stage_dist = stage_root / "dist"
        # PyInstaller keeps its analysis in the work folder and reuses it
        # when little has changed. A fresh folder each time made every
        # update analyse all 150 MB of libraries again. This is the same
        # folder scripts\build-exe.bat uses, so either build warms the other.
        stage_work = repo / "build"
        stage_dist.mkdir(parents=True, exist_ok=True)
        stage_work.mkdir(parents=True, exist_ok=True)
        build_done = run_cmd(
            [
                str(py_exe),
                "-m",
                "PyInstaller",
                str(repo / "packaging" / "babysitter.spec"),
                "--noconfirm",
                "--distpath",
                str(stage_dist),
                "--workpath",
                str(stage_work),
            ],
            timeout=600,
            cwd=repo,
            env=clean_pyinstaller_env(),
        )
        if build_done.returncode != 0:
            shutil.rmtree(stage_root, ignore_errors=True)
            tail = (build_done.stderr or build_done.stdout or "").strip().splitlines()
            reason = tail[-1] if tail else "PyInstaller exited with an error"
            raise UpdateError(f"Could not rebuild BabySitter.exe ({reason}).")

        exe_name = "BabySitter.exe" if sys.platform == "win32" else "BabySitter"
        built_file = stage_dist / exe_name
        if not built_file.is_file():
            shutil.rmtree(stage_root, ignore_errors=True)
            raise UpdateError("PyInstaller finished without creating BabySitter.exe.")

        staged_dest = updates_dir() / ("BabySitter-new.exe" if sys.platform == "win32" else "BabySitter-new")
        shutil.copy2(built_file, staged_dest)
        shutil.rmtree(stage_root, ignore_errors=True)
        staged_exe_str = str(staged_dest)

    on_step("Preparing clean restart…")
    if is_frozen:
        own_exe = str(Path(sys.executable).resolve())
        targets = [own_exe]
        if dist_exe.parent.is_dir() and str(dist_exe).lower() != own_exe.lower():
            targets.append(str(dist_exe))
        manifest = write_update_manifest(
            from_version=plan.current_version,
            to_version=new_version,
            staged_exe=staged_exe_str,
            targets=targets,
            relaunch_cmd=[own_exe],
            relaunch_cwd=str(Path(own_exe).parent),
        )
        return PreparedUpdate(
            message=f"Update {new_version} is ready. Restarting BabySitter…",
            manifest_path=manifest,
            helper_cmd=[staged_exe_str],
            helper_env={},
        )

    targets = [str(dist_exe)] if staged_exe_str else []
    vbs_launcher = repo / "Run BabySitter.vbs"
    if sys.platform == "win32" and vbs_launcher.is_file():
        relaunch_cmd = ["wscript.exe", str(vbs_launcher)]
        relaunch_env: dict[str, str] = {}
    else:
        relaunch_cmd = [sys.executable, "-m", "babysitter"]
        relaunch_env = {"PYTHONPATH": str(repo / "src")}

    helper_env = {"PYTHONPATH": str(repo / "src")}
    manifest = write_update_manifest(
        from_version=plan.current_version,
        to_version=new_version,
        staged_exe=staged_exe_str,
        targets=targets,
        relaunch_cmd=relaunch_cmd,
        relaunch_cwd=str(repo),
        relaunch_env=relaunch_env,
    )
    return PreparedUpdate(
        message=f"Update {new_version} is ready. Restarting BabySitter…",
        manifest_path=manifest,
        helper_cmd=[sys.executable, "-m", "babysitter"],
        helper_env=helper_env,
    )


def _prepare_github_update(
    plan: UpdatePlan,
    *,
    is_frozen: bool,
    on_step,
    opener=None,
    signature_runner=None,
) -> PreparedUpdate:
    if not plan.asset_url or not plan.asset_sha256 or not plan.asset_name:
        raise UpdateError("This release does not include a verified Windows installer yet.")
    require_release_asset_url(plan.asset_url)

    folder = updates_dir()
    safe_name = Path(plan.asset_name).name
    part_path = folder / (safe_name + ".part")
    open_url = opener or urllib.request.urlopen
    request = urllib.request.Request(plan.asset_url, headers={"User-Agent": "BabySitter"})

    on_step(f"Downloading {safe_name} from GitHub…")
    total = 0
    try:
        with open_url(request, timeout=30) as response, open(part_path, "wb") as handle:
            while True:
                chunk = response.read(512 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_RELEASE_BYTES:
                    raise UpdateError("That release file was larger than expected. Nothing was kept.")
                handle.write(chunk)
    except UpdateError:
        part_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        part_path.unlink(missing_ok=True)
        raise UpdateError("Download stopped before finishing. Nothing was changed.") from exc

    on_step("Verifying SHA-256 fingerprint…")
    try:
        require_sha256_file(plan.asset_sha256, part_path)
    except ValueError as exc:
        part_path.unlink(missing_ok=True)
        raise UpdateError(str(exc)) from exc

    if plan.asset_kind == "installer":
        # Phase 7: an installer runs with your rights and changes Program Files,
        # so the hash is not enough. Windows must also accept its code signature.
        on_step("Checking the installer's code signature…")
        from babysitter.signature import SignatureError, require_signed

        try:
            require_signed(part_path, run_cmd=signature_runner) if signature_runner else require_signed(part_path)
        except SignatureError as exc:
            part_path.unlink(missing_ok=True)
            raise UpdateError(str(exc)) from exc
        final_path = folder / safe_name
        os.replace(part_path, final_path)
        helper_cmd = (
            [str(Path(sys.executable).resolve())]
            if is_frozen
            else [sys.executable, "-m", "babysitter"]
        )
        helper_env = {} if is_frozen else {"PYTHONPATH": str(project_root() / "src")}
        manifest = write_update_manifest(
            from_version=plan.current_version,
            to_version=plan.target_version,
            relaunch_cmd=[],
            installer_exe=str(final_path),
        )
        return PreparedUpdate(
            message=f"Verified {safe_name}. Closing BabySitter to install {plan.target_version}…",
            manifest_path=manifest,
            helper_cmd=helper_cmd,
            helper_env=helper_env,
        )

    final_path = folder / "BabySitter-new.exe"
    os.replace(part_path, final_path)
    own_exe = str(Path(sys.executable).resolve())
    manifest = write_update_manifest(
        from_version=plan.current_version,
        to_version=plan.target_version,
        staged_exe=str(final_path),
        targets=[own_exe],
        relaunch_cmd=[own_exe],
        relaunch_cwd=str(Path(own_exe).parent),
    )
    return PreparedUpdate(
        message=f"Verified {plan.target_version}. Restarting BabySitter…",
        manifest_path=manifest,
        helper_cmd=[str(final_path)],
        helper_env={},
    )


def prepare_update(
    plan: UpdatePlan,
    *,
    on_step=None,
    opener=None,
    frozen: bool | None = None,
    run_cmd=run_hidden,
) -> PreparedUpdate:
    """Apply or stage the update in the background so BabySitter can restart into it."""
    if not plan.available or not plan.can_install:
        raise UpdateError(plan.summary or "No installable update is waiting right now.")
    shown = on_step or (lambda _msg: None)
    started = time.monotonic()

    def step(message: str) -> None:
        # Each step goes in the log with the seconds so far, so a slow or
        # stuck update shows where the time went.
        try:
            from babysitter.logsetup import get_logger

            get_logger().info("Update +%.0fs: %s", time.monotonic() - started, message)
        except Exception:
            pass
        shown(message)

    is_frozen = running_inside_exe() if frozen is None else frozen
    if plan.source == "git":
        return _prepare_git_update(plan, is_frozen=is_frozen, on_step=step, run_cmd=run_cmd)
    if plan.source == "github":
        return _prepare_github_update(plan, is_frozen=is_frozen, on_step=step, opener=opener)
    raise UpdateError("Unknown update source.")
