"""Logging setup: a single rotating file, since the TUI owns the terminal.

Every module logs via `logging.getLogger(__name__)`; those all nest under the
"reddit_reader" logger configured here and inherit its handler and level.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from reddit_reader.config import Settings

_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5

_configured = False


def configure_logging(settings: Settings) -> None:
    """Attach a rotating file handler to the package logger.

    Safe to call more than once (e.g. across multiple CLI invocations in the
    same process, as in tests) — only the first call takes effect.
    """
    global _configured
    if _configured:
        return
    _configured = True

    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(settings.log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger = logging.getLogger("reddit_reader")
    logger.setLevel(level)
    logger.addHandler(handler)
    # Never hand records to the root logger — nothing configures it, and
    # printing to stderr would corrupt the TUI's own screen control.
    logger.propagate = False
