"""Tests do not open a real window on the desktop."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# On Windows the offscreen platform finds no fonts on its own, so every
# text measures far too wide and the layout tests fail. Point it at the
# Windows font folder so it measures the way the real window does.
if sys.platform == "win32":
    fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    if os.path.isdir(fonts):
        os.environ.setdefault("QT_QPA_FONTDIR", fonts)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _never_open_real_files(monkeypatch):
    """No test may open a file on this PC.

    A test that says "open number 1" used to call Windows' real os.startfile,
    so every run opened helmet.stl in whatever program owns .stl files (on
    Alex's PC, Creality Print, eight copies in one evening). Opening is
    recorded here instead, and a test can read the list.
    """
    opened: list[str] = []
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", lambda path, *args, **kwargs: opened.append(str(path)))
    # Web pages and local files opened through Qt or the webbrowser module
    # are recorded the same way, so no test opens the real browser either.
    import webbrowser

    def _record_url(url, *args, **kwargs):
        opened.append(str(url.toString() if hasattr(url, "toString") else url))
        return True

    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, name, _record_url)
    try:
        from PySide6.QtGui import QDesktopServices

        monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(_record_url))
    except ImportError:
        pass
    return opened
