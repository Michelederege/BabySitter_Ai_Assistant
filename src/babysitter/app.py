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
from babysitter.ui.theme import MAIN_QSS, apply_fonts


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    if len(args) >= 3 and args[1] == "--finish-update":
        from babysitter.selfupdate import run_finish_update

        return run_finish_update(args[2])
    try:
        return _run(args)
    except Exception:
        text = traceback.format_exc()
        try:
            setup_logging()
            get_logger().error("Startup failed:\n%s", text)
        except Exception:
            pass
        from babysitter.startup_error import show_startup_failure

        show_startup_failure(text)
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
    apply_fonts(app)
    font = QFont()
    font.setFamilies(["Inter", "Segoe UI", "Ubuntu", "DejaVu Sans", "sans-serif"])
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(MAIN_QSS)
    app.setWindowIcon(load_icon())

    instance = SingleInstance()
    if not instance.primary:
        return 0

    controller = Controller()
    shell = Shell(controller)
    shell.single_instance = instance
    try:
        instance.asked_to_raise.connect(shell.show_window)
        shell.show()
        from babysitter.selfupdate import consume_completed_update

        updated_note = consume_completed_update()
        if updated_note:
            shell.note_completed_update(updated_note)
        sys.excepthook = _hook
        return app.exec()
    finally:
        try:
            shell.registrar.clear()
        except Exception:
            pass
        instance.release()
        controller.shutdown_threads()


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
