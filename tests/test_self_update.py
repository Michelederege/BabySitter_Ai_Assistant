from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess

import pytest
from PySide6.QtWidgets import QApplication

from babysitter.commands import match_quick_command
from babysitter.security import require_release_asset_url, require_sha256_file
from babysitter.selfupdate import (
    clean_pyinstaller_env,
    consume_completed_update,
    remember_repo_path,
    run_finish_update,
    saved_repo_path,
    updates_dir,
    write_update_manifest,
)
from babysitter.single_instance import SingleInstance
from babysitter.ui.pages.settings_page import SettingsPage
from babysitter.updates import (
    UpdateError,
    check_for_update,
    find_git_repo,
    prepare_update,
)


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return (done.stdout or "").strip()


def _make_origin_and_clone(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a bare origin repo and two clones: publisher and local C:\\BabySitter stand-in."""
    origin = tmp_path / "origin.git"
    publisher = tmp_path / "publisher"
    local = tmp_path / "local-babysitter"

    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    _git(tmp_path, "clone", str(origin), str(publisher))
    for folder in (publisher,):
        _git(folder, "config", "user.name", "Test")
        _git(folder, "config", "user.email", "test@example.com")

    (publisher / "packaging").mkdir(parents=True)
    (publisher / "packaging" / "babysitter.spec").write_text("# spec\n", encoding="utf-8")
    (publisher / "src" / "babysitter").mkdir(parents=True)
    (publisher / "src" / "babysitter" / "version.py").write_text(
        '__version__ = "0.17.4"\n',
        encoding="utf-8",
    )
    (publisher / "requirements.txt").write_text("psutil\n", encoding="utf-8")
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-m", "Initial 0.17.4")
    _git(publisher, "branch", "-M", "main")
    _git(publisher, "push", "-u", "origin", "main")

    _git(tmp_path, "clone", str(origin), str(local))
    _git(local, "config", "user.name", "Test")
    _git(local, "config", "user.email", "test@example.com")
    return origin, publisher, local


def test_git_origin_update_check_pull_and_relaunch(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "appdata"))
    _origin, publisher, local = _make_origin_and_clone(tmp_path)
    monkeypatch.setenv("BABYSITTER_REPO_DIR", str(local))

    up_to_date = check_for_update(current="0.17.4", frozen=False)
    assert up_to_date.available is False
    assert up_to_date.source == "git"
    assert saved_repo_path() == local.resolve()

    (publisher / "README.md").write_text("First merged PR\n", encoding="utf-8")
    _git(publisher, "add", "README.md")
    _git(publisher, "commit", "-m", "Add voice polish (#32)")
    (publisher / "src" / "babysitter" / "version.py").write_text(
        '__version__ = "0.18.0"\n',
        encoding="utf-8",
    )
    _git(publisher, "add", "src/babysitter/version.py")
    _git(publisher, "commit", "-m", "Ship in-app updater (0.18.0) (#33)")
    _git(publisher, "push", "origin", "main")

    plan = check_for_update(current="0.17.4", frozen=False)
    assert plan.available is True
    assert plan.can_install is True
    assert plan.source == "git"
    assert plan.target_version == "0.18.0"
    assert plan.commits_behind == 2
    assert any("0.18.0" in line for line in plan.headlines)

    steps: list[str] = []
    prepared = prepare_update(plan, on_step=steps.append, frozen=False)
    assert steps
    assert '0.18.0' in (local / "src" / "babysitter" / "version.py").read_text(encoding="utf-8")
    assert prepared.manifest_path.is_file()

    launched: list[tuple[list[str], dict]] = []
    rc = run_finish_update(
        str(prepared.manifest_path),
        sleep_fn=lambda _s: None,
        pid_exists_fn=lambda _pid: False,
        popen_fn=lambda args, **kw: launched.append((args, kw)),
    )
    assert rc == 0
    assert len(launched) == 1
    assert launched[0][1]["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"

    banner = consume_completed_update("0.18.0")
    assert "0.17.4" in banner and "0.18.0" in banner
    assert consume_completed_update("0.18.0") == ""


def test_dirty_local_repo_never_overwrites_unsaved_work(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "appdata"))
    _origin, publisher, local = _make_origin_and_clone(tmp_path)
    monkeypatch.setenv("BABYSITTER_REPO_DIR", str(local))

    (publisher / "src" / "babysitter" / "version.py").write_text(
        '__version__ = "0.18.0"\n',
        encoding="utf-8",
    )
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-m", "Bump to 0.18.0")
    _git(publisher, "push", "origin", "main")

    (local / "requirements.txt").write_text("psutil\n# local edit\n", encoding="utf-8")
    plan = check_for_update(current="0.17.4", frozen=False)
    assert plan.available is True
    assert plan.can_install is False
    assert "requirements.txt" in plan.dirty_files
    with pytest.raises(UpdateError):
        prepare_update(plan, frozen=False)


def test_frozen_exe_detects_stale_build_commit_and_swaps_both_exes(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "appdata"))
    _origin, publisher, local = _make_origin_and_clone(tmp_path)
    monkeypatch.setenv("BABYSITTER_REPO_DIR", str(local))

    old_sha = _git(local, "rev-parse", "HEAD")
    (publisher / "src" / "babysitter" / "version.py").write_text(
        '__version__ = "0.18.0"\n',
        encoding="utf-8",
    )
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-m", "Release 0.18.0")
    _git(publisher, "push", "origin", "main")
    # Even if local repo was already pulled earlier, an older Desktop BabySitter.exe
    # compiled from old_sha still notices it is behind origin/main!
    _git(local, "pull", "--ff-only", "origin", "main")

    plan = check_for_update(current="0.17.4", frozen=True, built_commit=old_sha)
    assert plan.available is True
    assert plan.can_install is True
    assert plan.needs_exe_rebuild is True

    staged = updates_dir() / "BabySitter-new.exe"
    staged.write_bytes(b"NEW-EXE-0.18.0")
    desktop_exe = tmp_path / "Desktop" / "BabySitter.exe"
    desktop_exe.parent.mkdir(parents=True)
    desktop_exe.write_bytes(b"OLD-EXE-0.17.4")
    dist_exe = local / "dist" / "BabySitter.exe"
    dist_exe.parent.mkdir(parents=True)
    dist_exe.write_bytes(b"OLD-DIST-0.17.4")

    manifest = write_update_manifest(
        from_version="0.17.4",
        to_version="0.18.0",
        staged_exe=str(staged),
        targets=[str(desktop_exe), str(dist_exe)],
        relaunch_cmd=[str(desktop_exe)],
        wait_pids=[999999],
    )
    alive_checks = [True, True, False]
    relaunched: list[list[str]] = []
    rc = run_finish_update(
        str(manifest),
        sleep_fn=lambda _s: None,
        pid_exists_fn=lambda _pid: alive_checks.pop(0) if alive_checks else False,
        popen_fn=lambda args, **_kw: relaunched.append(args),
    )
    assert rc == 0
    assert desktop_exe.read_bytes() == b"NEW-EXE-0.18.0"
    assert dist_exe.read_bytes() == b"NEW-EXE-0.18.0"
    assert relaunched == [[str(desktop_exe)]]


def test_github_release_fallback_verifies_sha256_and_rejects_tampering(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setenv("BABYSITTER_REPO_DIR", "none")
    assert find_git_repo() is None

    exe_bytes = b"MZ-verified-babysitter-0.19.0-binary"
    good_hash = hashlib.sha256(exe_bytes).hexdigest()
    asset_url = (
        "https://github.com/Michelederege/BabySitter_Ai_Assistant/"
        "releases/download/v0.19.0/BabySitter.exe"
    )
    release_json = json.dumps(
        {
            "tag_name": "v0.19.0",
            "html_url": "https://github.com/Michelederege/BabySitter_Ai_Assistant/releases/tag/v0.19.0",
            "assets": [
                {
                    "name": "BabySitter.exe",
                    "browser_download_url": asset_url,
                    "digest": f"sha256:{good_hash}",
                }
            ],
        }
    ).encode("utf-8")

    def make_opener(binary_payload: bytes):
        @contextlib.contextmanager
        def opener(req, timeout=0):
            del timeout
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("/releases/latest"):
                yield io.BytesIO(release_json)
            elif url == asset_url:
                yield io.BytesIO(binary_payload)
            else:
                raise AssertionError(f"Unexpected URL: {url}")

        return opener

    plan = check_for_update(
        current="0.18.0",
        frozen=True,
        opener=make_opener(exe_bytes),
    )
    assert plan.available is True
    assert plan.source == "github"
    assert plan.can_install is True
    assert plan.asset_sha256 == good_hash

    with pytest.raises(UpdateError, match="SHA-256"):
        prepare_update(plan, frozen=True, opener=make_opener(b"tampered-binary"))
    assert not list(updates_dir().glob("*.part"))

    prepared = prepare_update(plan, frozen=True, opener=make_opener(exe_bytes))
    assert (updates_dir() / "BabySitter-new.exe").read_bytes() == exe_bytes
    assert prepared.manifest_path.is_file()


def test_release_security_guards_and_pyinstaller_env(tmp_path):
    require_release_asset_url(
        "https://github.com/Michelederege/BabySitter_Ai_Assistant/releases/download/v1.0.0/BabySitter.exe"
    )
    for bad in (
        "http://github.com/Michelederege/BabySitter_Ai_Assistant/releases/download/v1/BabySitter.exe",
        "https://github.com/someone-else/other/releases/download/v1/BabySitter.exe",
        "https://evil.example.com/BabySitter.exe",
    ):
        with pytest.raises(ValueError):
            require_release_asset_url(bad)

    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"hello")
    require_sha256_file(hashlib.sha256(b"hello").hexdigest(), sample)
    with pytest.raises(ValueError):
        require_sha256_file("0" * 64, sample)

    env = clean_pyinstaller_env({"CUSTOM": "1"})
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "_MEIPASS" not in env
    assert "_MEIPASS2" not in env
    assert env["CUSTOM"] == "1"


def test_quick_commands_settings_buttons_and_single_instance_release(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "appdata"))
    remember_repo_path(tmp_path)

    check_cmd = match_quick_command("Hey BabySitter, check for updates please")
    assert check_cmd is not None and check_cmd.kind == "check_update"
    apply_cmd = match_quick_command("update babysitter")
    assert apply_cmd is not None and apply_cmd.kind == "apply_update"

    app = QApplication.instance() or QApplication([])
    page = SettingsPage()
    assert page.check_updates.text() == "Check for an update"
    assert page.install_update.text() == "Update BabySitter"
    assert "no git push" in page.update_status.text()

    key = f"BabySitter.test.{tmp_path.name}"
    first = SingleInstance(key=key)
    assert first.primary is True
    blocked = SingleInstance(key=key)
    assert blocked.primary is False
    first.release()
    reopened = SingleInstance(key=key)
    assert reopened.primary is True
    reopened.release()
    assert app is not None


def test_a_failed_swap_still_reopens_the_old_version(tmp_path, monkeypatch):
    import babysitter.selfupdate as selfupdate

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    desktop_exe = tmp_path / "Desktop" / "BabySitter.exe"
    desktop_exe.parent.mkdir(parents=True)
    desktop_exe.write_bytes(b"OLD")
    staged = tmp_path / "data" / "updates" / "BabySitter-new.exe"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"NEW")

    def locked(_source, _target, **_kw):
        raise PermissionError("in use")

    monkeypatch.setattr(selfupdate, "_replace_with_retries", locked)
    for staged_path in (str(staged), str(tmp_path / "missing.exe")):
        manifest = write_update_manifest(
            from_version="0.19.1",
            to_version="0.19.2",
            staged_exe=staged_path,
            targets=[str(desktop_exe)],
            relaunch_cmd=[str(desktop_exe)],
            wait_pids=[],
        )
        relaunched: list[list[str]] = []
        rc = run_finish_update(
            str(manifest),
            sleep_fn=lambda _s: None,
            pid_exists_fn=lambda _pid: False,
            popen_fn=lambda args, **_kw: relaunched.append(args),
        )
        assert rc == 1
        assert relaunched == [[str(desktop_exe)]]
        assert desktop_exe.read_bytes() == b"OLD"
        note = consume_completed_update("0.19.1")
        assert note.startswith("The update did not finish.")
        assert "old" in note


def test_a_failed_pull_puts_the_folder_back_on_its_branch(tmp_path, monkeypatch):
    from babysitter.updates import UpdateError

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "appdata"))
    _origin, publisher, local = _make_origin_and_clone(tmp_path)
    monkeypatch.setenv("BABYSITTER_REPO_DIR", str(local))

    # Local main has a commit Origin does not, so a fast-forward fails.
    (local / "LOCAL.md").write_text("only here\n", encoding="utf-8")
    _git(local, "add", "LOCAL.md")
    _git(local, "commit", "-m", "Local only")
    _git(local, "checkout", "-b", "my-work")
    (publisher / "README.md").write_text("New on Origin\n", encoding="utf-8")
    _git(publisher, "add", "README.md")
    _git(publisher, "commit", "-m", "New on Origin")
    _git(publisher, "push", "origin", "main")

    plan = check_for_update(current="0.17.4", frozen=False)
    assert plan.available is True
    with pytest.raises(UpdateError):
        prepare_update(plan, on_step=lambda _s: None, frozen=False)
    branch = subprocess.run(
        ["git", "-C", str(local), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert branch == "my-work"


def test_a_stuck_old_copy_is_closed_before_the_new_one_opens(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    manifest = write_update_manifest(
        from_version="0.20.0", to_version="0.20.1", relaunch_cmd=["BabySitter.exe"], wait_pids=[4242],
    )
    alive = {4242: True}
    closed: list = []
    order: list[str] = []

    def close(pids):
        closed.extend(pids)
        order.append("closed")
        alive[4242] = False

    rc = run_finish_update(
        str(manifest),
        sleep_fn=lambda _s: None,
        pid_exists_fn=lambda pid: alive.get(pid, False),
        popen_fn=lambda args, **_kw: order.append("opened"),
        close_fn=close,
    )
    assert rc == 0
    assert closed == [4242]
    assert order == ["closed", "opened"]


def test_an_update_quits_even_when_turning_off_reports_a_problem(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    from babysitter.controller import Controller
    from babysitter.power import ERROR, PowerResult

    controller = Controller()
    fired: list = []
    controller.quit_ready.connect(lambda: fired.append(True))
    controller._quit_after_off = True
    controller._apply(PowerResult(ERROR, "Something is still listening on port 11434.", False))
    assert fired == []  # a normal quit stays open and says why
    controller._quit_after_off = True
    controller.force_quit = True
    controller._apply(PowerResult(ERROR, "Something is still listening on port 11434.", False))
    assert fired == [True]
