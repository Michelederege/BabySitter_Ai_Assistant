"""Tests do not open a real window on the desktop."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
