"""Lets you run `python -m babysitter`."""

import os
import traceback

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")


def _start() -> int:
    try:
        from babysitter.app import main
    except Exception:
        from babysitter.startup_error import show_startup_failure

        show_startup_failure(traceback.format_exc())
        return 1
    return main()


if __name__ == "__main__":
    raise SystemExit(_start())
