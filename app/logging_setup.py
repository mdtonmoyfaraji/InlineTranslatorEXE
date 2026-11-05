"""File logging for a windowed (console-less) app. The API key is never logged."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .settings import config_dir


def log_path() -> Path:
    return config_dir() / "app.log"


def setup_logging() -> None:
    root = logging.getLogger("inline_translator")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    try:
        h = RotatingFileHandler(log_path(), maxBytes=256_000, backupCount=1, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(h)
    except OSError:
        pass

    def hook(exc_type, exc, tb):
        root.error("Unhandled exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = hook
