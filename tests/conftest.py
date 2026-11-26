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
