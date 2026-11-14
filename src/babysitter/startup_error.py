"""Shows a startup failure even when no console window is open."""

from __future__ import annotations

import sys

from babysitter.paths import logs_dir


def show_startup_failure(text: str) -> None:
    """Write the crash text and, on Windows, open a message box.

    pythonw has no console. Without this, a failed double-click looks like
    the starter did nothing.
    """
    body = (text or "BabySitter could not start.").strip()
    message = (
        "BabySitter could not start. Copy this text and send it to me.\n\n" + body[-1800:]
    )
    try:
        (logs_dir() / "startup-error.txt").write_text(body, encoding="utf-8")
    except OSError:
        pass
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "BabySitter", 0x00000010)
        return
    sys.stderr.write(message + "\n")
