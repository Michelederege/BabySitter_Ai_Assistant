"""Writes a small log that never contains a conversation.

Phase 1 has no conversations yet. Later phases must keep transcripts out
of this file. The log is for "what the power switch did" and crash text,
so you can copy it when something breaks.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from babysitter.paths import logs_dir


LOG_NAME = "babysitter"
_CONFIGURED = False


def setup_logging() -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger(LOG_NAME)
    logger.setLevel(logging.INFO)
    if _CONFIGURED:
        return logger
    logger.propagate = False
    try:
        handler = RotatingFileHandler(
            logs_dir() / "babysitter.log",
            maxBytes=512_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
    except OSError:
        # The window can still run if the log folder is not writable.
        pass
    _CONFIGURED = True
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOG_NAME)
