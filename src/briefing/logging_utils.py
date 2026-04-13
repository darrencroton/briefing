"""Logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path

from .settings import AppSettings
from .utils import ensure_directory


def configure_logging(settings: AppSettings) -> None:
    """Configure console and file logging."""
    ensure_directory(settings.paths.log_dir)
    last_run_path = settings.paths.log_dir / settings.logging.last_run_file
    history_path = settings.paths.log_dir / settings.logging.history_file

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, settings.logging.level.upper(), logging.INFO))

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    last_run_handler = logging.FileHandler(last_run_path, mode="w", encoding="utf-8")
    last_run_handler.setFormatter(formatter)
    root.addHandler(last_run_handler)

    history_handler = logging.FileHandler(history_path, mode="a", encoding="utf-8")
    history_handler.setFormatter(formatter)
    root.addHandler(history_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)

