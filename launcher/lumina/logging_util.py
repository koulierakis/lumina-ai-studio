"""Logging helpers with size-limited rotating file handlers."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .paths import logs_dir


def setup_logging(level: str = "INFO", repo_root: Path | None = None) -> Path:
    log_path = logs_dir(repo_root) / "runtime.log"
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers when CLI commands re-enter
    marker = "lumina-runtime-file"
    if not any(getattr(h, "lumina_marker", None) == marker for h in root.handlers):
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        file_handler.lumina_marker = marker  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root.addHandler(stream)

    return log_path
