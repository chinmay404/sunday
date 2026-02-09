"""
Centralized logging configuration for the Sunday agent.

Import and call setup_logging() once at startup (main.py / api.py).
Every module then just does:
    import logging
    logger = logging.getLogger(__name__)
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
LOG_DATE_FMT = "%H:%M:%S"


def setup_logging(level: str | None = None) -> None:
    """
    Call once at process startup. Sets root logger format + level.
    Level is read from LOG_LEVEL env var (default: INFO).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    chosen = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    numeric = getattr(logging, chosen, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FMT))

    # File handler — rotates at 5 MB, keeps 3 backups
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "sunday.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FMT))

    root = logging.getLogger()
    root.setLevel(numeric)
    root.handlers.clear()
    root.addHandler(handler)
    root.addHandler(file_handler)

    # Quiet down noisy libraries
    for noisy in ("httpx", "httpcore", "urllib3", "google", "google_genai", "googleapiclient", "hpack", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
