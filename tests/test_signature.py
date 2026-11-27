"""NEXT_ROUND phase 7: an unsigned installer is refused."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from babysitter.signature import SignatureError, _common_name, require_signed


def _runner(status: str, subject: str = ""):
    def run(args, timeout=0, env=None):
        assert "BABYSITTER_SIGNED_FILE" in env  # the path travels outside the command text
        assert all("BABYSITTER_SIGNED_FILE" not in part or "$env:" in part for part in args)
        return SimpleNamespace(stdout=f"{status}\n{subject}\n", stderr="", returncode=0)

    return run


def test_only_a_valid_signature_from_the_right_publisher_passes(tmp_path):
    path = tmp_path / "BabySitter-Setup.exe"
    path.write_bytes(b"MZ")
    with pytest.raises(SignatureError, match="not code-signed"):
        require_signed(path, run_cmd=_runner("NotSigned"))
    with pytest.raises(SignatureError, match="HashMismatch"):
        require_signed(path, run_cmd=_runner("HashMismatch", "CN=Example Publisher"))
    assert require_signed(path, publisher="Example Publisher", run_cmd=_runner("Valid", 'CN="Example Publisher", O=Home')) == "Example Publisher"
    with pytest.raises(SignatureError, match="not by Example Publisher"):
        require_signed(path, publisher="Example Publisher", run_cmd=_runner("Valid", "CN=Someone Else"))
    assert _common_name("CN=A B, O=C") == "A B"


@pytest.mark.skipif(sys.platform != "win32", reason="Authenticode is Windows only")
def test_windows_really_tells_signed_from_unsigned(tmp_path):
    from babysitter.signature import authenticode

    unsigned = tmp_path / "plain.exe"
    unsigned.write_bytes(b"MZ" + b"\0" * 200)
    assert authenticode(unsigned)[0] in {"NotSigned", "UnknownError"}
    signed = Path(r"C:\Windows\System32\notepad.exe")
    if signed.is_file():
        assert authenticode(signed)[0] == "Valid"


def test_the_updater_deletes_an_unsigned_installer(tmp_path, monkeypatch):
    import contextlib
    import hashlib

    from babysitter import updates

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    payload = b"MZ fake installer"
    plan = updates.UpdatePlan(
        available=True,
        source="github",
        current_version="0.27.0",
        target_version="v0.28.0",
        asset_url="https://github.com/Michelederege/BabySitter_Ai_Assistant/releases/download/v0.28.0/BabySitter-Setup-0.28.0.exe",
        asset_name="BabySitter-Setup-0.28.0.exe",
        asset_sha256=hashlib.sha256(payload).hexdigest(),
        asset_kind="installer",
        can_install=True,
    )

    @contextlib.contextmanager
    def opener(request, timeout=0):
        chunks = [payload, b""]

        class Response:
            def read(self, _size):
                return chunks.pop(0)

        yield Response()

    steps: list = []
    with pytest.raises(updates.UpdateError, match="not code-signed"):
        updates._prepare_github_update(plan, is_frozen=True, on_step=steps.append, opener=opener, signature_runner=_runner("NotSigned"))
    assert "Checking the installer's code signature…" in steps
    assert not list(updates.updates_dir().glob("BabySitter-Setup*"))
