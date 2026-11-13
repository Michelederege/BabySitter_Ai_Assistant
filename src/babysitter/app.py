"""Starts BabySitter. The AI is off until you turn it on."""

from __future__ import annotations

import ctypes
import sys
import traceback

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from babysitter.controller import Controller
from babysitter.logsetup import get_logger, setup_logging
from babysitter.platform import prefer_per_monitor_dpi, set_windows_app_id
from babysitter.single_instance import SingleInstance
from babysitter.ui.shell import Shell, load_icon
from babysitter.ui.theme import MAIN_QSS


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(list(sys.argv if argv is None else argv))
    except Exception:
        text = traceback.format_exc()
        try:
            setup_logging()
            get_logger().error("Startup failed:\n%s", text)
        except Exception:
            pass
        panic(text)
        return 1


def _run(argv: list[str]) -> int:
    # DPI and the taskbar id must be set before the window toolkit starts.
    prefer_per_monitor_dpi()
    set_windows_app_id()
    setup_logging()
    app = QApplication(argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("BabySitter")
    app.setOrganizationName("BabySitter")
    font = QFont()
    font.setFamilies(["Segoe UI", "Inter", "Ubuntu", "DejaVu Sans", "sans-serif"])
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(MAIN_QSS)
    app.setWindowIcon(load_icon())

    instance = SingleInstance()
    if not instance.primary:
        return 0

    controller = Controller()
    shell = Shell(controller)
    instance.asked_to_raise.connect(shell.show_window)
    shell.show()
    sys.excepthook = _hook
    return app.exec()


def _hook(exc_type, value, tb) -> None:
    text = "".join(traceback.format_exception(exc_type, value, tb))
    try:
        get_logger().error("Unhandled error:\n%s", text)
    except Exception:
        pass
    panic(text)


def panic(text: str) -> None:
    message = (
        "BabySitter hit an error. Copy this text and send it to me.\n\n" + text[-1800:]
    )
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "BabySitter", 0x00000010)
    else:
        sys.stderr.write(message + "\n")
