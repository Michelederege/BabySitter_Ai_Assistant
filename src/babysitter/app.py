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
    from babysitter.settings import SettingsError

    try:
        return _run(args)
    except SettingsError as exc:
        # A plain sentence, such as settings from a newer BabySitter.
        # A traceback here only hides the one line that matters.
        from babysitter.startup_error import show_startup_failure

        show_startup_failure(str(exc))
        return 1
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
        install_error_hooks()
        return app.exec()
    finally:
        try:
            shell.registrar.clear()
        except Exception:
            pass
        instance.release()
        controller.shutdown_threads()


# The same error shown again and again is a wall of boxes, not help: on
# 26 Nov one missing file in an old exe raised 18 boxes in two minutes.
# Each different error is shown once per run; every one is still logged.
_shown: set[str] = set()
_crash_file = None


def install_error_hooks() -> None:
    """Catch errors from the window, from background threads, and hard crashes.

    - The window and Qt jobs: logged, and shown once per kind (`_hook`).
    - Plain Python threads (keyword listening, the voice player): logged only.
      Before this they vanished, since the exe has no console to print to.
    - A crash inside a library written in C (audio, onnx) kills Python with
      no traceback. faulthandler writes the stack of every thread to
      logs/crash.log first, so there is something to read afterwards.
    """
    import threading

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    _enable_crash_log()


def _enable_crash_log() -> None:
    global _crash_file
    import faulthandler

    from babysitter.paths import logs_dir

    try:
        path = logs_dir() / "crash.log"
        if path.is_file() and path.stat().st_size > 512_000:
            path.replace(path.with_name("crash.log.1"))
        _crash_file = open(path, "a", encoding="utf-8")  # kept open: faulthandler writes to it at the crash
        faulthandler.enable(_crash_file, all_threads=True)
    except Exception:  # noqa: BLE001 - no crash log is better than no window
        _crash_file = None


def _error_key(exc_type, tb) -> str:
    """The kind of error and the line it came from, so repeats are recognised."""
    where = traceback.extract_tb(tb)[-1:] if tb is not None else []
    spot = f"{where[0].filename}:{where[0].lineno}" if where else ""
    return f"{getattr(exc_type, '__name__', exc_type)}@{spot}"


def _hook(exc_type, value, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return  # Ctrl+C while closing a console run is not a bug worth a box
    text = "".join(traceback.format_exception(exc_type, value, tb))
    try:
        get_logger().error("Unhandled error:\n%s", text)
    except Exception:
        pass
    key = _error_key(exc_type, tb)
    if key in _shown:
        return
    _shown.add(key)
    panic(text)


def _thread_hook(args) -> None:
    if args.exc_type is SystemExit:
        return
    name = getattr(args.thread, "name", "a background thread")
    text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    try:
        get_logger().error("Unhandled error in %s:\n%s", name, text)
    except Exception:
        pass


def panic(text: str) -> None:
    message = (
        "BabySitter hit an error. Copy this text and send it to me.\n\n" + text[-1800:]
    )
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "BabySitter", 0x00000010)
    else:
        sys.stderr.write(message + "\n")
