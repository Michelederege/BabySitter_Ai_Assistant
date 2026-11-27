"""Code signatures on downloaded update files (NEXT_ROUND phase 7).

Windows' own check (Authenticode, through Get-AuthenticodeSignature) says
whether a file is signed by a certificate Windows trusts and has not been
changed since. The updater refuses an installer that is not signed, on top
of the SHA-256 check it already does.

EXPECTED_PUBLISHER is the name on the code-signing certificate. It is empty
until Alex buys one; then it is set here, and a file signed by anyone
else is refused too.

The file path is passed in an environment variable, never inside the
command text, so a name cannot change what PowerShell runs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from babysitter.platform import run_hidden

EXPECTED_PUBLISHER = ""  # set to the certificate's CN once it is bought, e.g. "Example Publisher"

_SCRIPT = (
    "$s = Get-AuthenticodeSignature -LiteralPath $env:BABYSITTER_SIGNED_FILE; "
    "$n = ''; if ($s.SignerCertificate) { $n = $s.SignerCertificate.Subject }; "
    "Write-Output ([string]$s.Status); Write-Output $n"
)


class SignatureError(Exception):
    """The file is not signed, or not by BabySitter's publisher. Nothing was installed."""


def authenticode(path: Path, run_cmd=run_hidden) -> tuple[str, str]:
    """(status, signer subject). Status is Windows' word: Valid, NotSigned, HashMismatch, ..."""
    if sys.platform != "win32" and run_cmd is run_hidden:
        return "NotSupported", ""
    env = dict(os.environ)
    env["BABYSITTER_SIGNED_FILE"] = str(Path(path).resolve())
    completed = run_cmd(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _SCRIPT],
        timeout=30,
        env=env,
    )
    lines = [line.strip() for line in (completed.stdout or "").splitlines()]
    status = lines[0] if lines else "Unknown"
    subject = lines[1] if len(lines) > 1 else ""
    return status, subject


def _common_name(subject: str) -> str:
    for part in (subject or "").split(","):
        key, _, value = part.strip().partition("=")
        if key.upper() == "CN":
            return value.strip().strip('"')
    return ""


def require_signed(path: Path, publisher: str = EXPECTED_PUBLISHER, run_cmd=run_hidden) -> str:
    """Return the signer's name, or raise SignatureError."""
    status, subject = authenticode(path, run_cmd=run_cmd)
    if status == "NotSigned":
        raise SignatureError("That installer is not code-signed, so it was not run. The release needs a signed installer.")
    if status != "Valid":
        raise SignatureError(f"Windows did not accept that installer's signature ({status}), so it was not run.")
    name = _common_name(subject)
    if publisher and name.casefold() != publisher.casefold():
        raise SignatureError(f"That installer is signed by {name or 'someone else'}, not by {publisher}, so it was not run.")
    return name
