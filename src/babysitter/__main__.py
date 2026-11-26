"""Lets you run `python -m babysitter`."""

import os
import sys
import traceback

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")


def _start() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--finish-update":
        from babysitter.selfupdate import run_finish_update

        return run_finish_update(sys.argv[2])
    try:
        from babysitter.app import main
    except Exception:
        from babysitter.startup_error import show_startup_failure

        show_startup_failure(traceback.format_exc())
        return 1
    return main()


if __name__ == "__main__":
    raise SystemExit(_start())
