"""Lets you run `python -m babysitter`."""

import os

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")

from babysitter.app import main

if __name__ == "__main__":
    raise SystemExit(main())
