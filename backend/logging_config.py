"""
Centralized logging configuration.

Provides a single `setup_logging()` call that configures a named logger
("student_support") with both a rotating file handler (for persistent,
reviewable logs as required by the assignment) and a console handler
(for live feedback during development).

Other modules retrieve the configured logger via `get_logger()`.
"""

import logging
from logging.handlers import RotatingFileHandler

from backend.config import settings

LOGGER_NAME = "student_support"

# Keep log files from growing unbounded: 1 MB per file, 3 backups kept.
MAX_LOG_BYTES = 1_000_000
BACKUP_COUNT = 3

_configured = False


def setup_logging() -> logging.Logger:
    """Configure and return the application's shared logger.

    Safe to call multiple times: configuration is only applied once per
    process, avoiding duplicate log handlers (and therefore duplicate log
    lines) if this function is imported from several modules.
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)

    if _configured:
        return logger

    log_path = settings.resolved_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        filename=str(log_path),
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.setLevel(settings.log_level.upper())
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False

    _configured = True
    return logger


def get_logger() -> logging.Logger:
    """Return the shared application logger, configuring it if needed."""
    return setup_logging()
