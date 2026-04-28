"""Project-local file logging with rotation.

All platforms log to the same place: ``<project_root>/logs/cc-buddy-bridge.log``.

Project root is resolved from this module's filesystem position:

    src/cc_buddy_bridge/logging_setup.py
    └── parent = .../cc_buddy_bridge/
        └── parent = .../src/
            └── parent = <project_root>/

This works for editable installs (``pip install -e .``) which is the
documented workflow. For non-editable installs the logs would land inside
site-packages — known trade-off, see plan §2.3.

The ``CC_BUDDY_BRIDGE_LOG_DIR`` env var overrides the directory if set.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE_NAME = "cc-buddy-bridge.log"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
BACKUP_COUNT = 5  # keep up to 5 rotated files (~50 MB total)
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def project_root() -> Path:
    """Resolve the project root from this file's location.

    ``src/cc_buddy_bridge/logging_setup.py`` → ``<project_root>``.
    """
    return Path(__file__).resolve().parent.parent.parent


def log_dir() -> Path:
    """Directory where logs are written.

    Honors ``CC_BUDDY_BRIDGE_LOG_DIR`` if set, otherwise ``<project_root>/logs``.
    """
    override = os.environ.get("CC_BUDDY_BRIDGE_LOG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return project_root() / "logs"


def log_path() -> Path:
    """Absolute path to the main log file."""
    return log_dir() / LOG_FILE_NAME


def tail_hint() -> str:
    """Platform-appropriate command for tailing the log file."""
    p = log_path()
    if sys.platform == "win32":
        return f"Get-Content -Wait '{p}'"
    return f"tail -f {p}"


def setup_logging(level: str = "INFO") -> Path:
    """Configure root logging: rotating file + stderr stream.

    Idempotent: removes any cc-buddy-bridge handlers we previously installed
    on the root logger before adding new ones, so re-calling (e.g. in tests)
    doesn't multiply handlers.

    Returns the resolved log file path so callers can print/show it.
    """
    target_level = getattr(logging, level.upper(), logging.INFO)

    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    file_path = directory / LOG_FILE_NAME

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        file_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(target_level)
    # Tag so we can find and replace on re-init.
    file_handler.set_name("cc-buddy-bridge.file")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(target_level)
    stream_handler.set_name("cc-buddy-bridge.stream")

    root = logging.getLogger()
    # Drop any handlers we previously installed (idempotency).
    for h in list(root.handlers):
        if h.name in ("cc-buddy-bridge.file", "cc-buddy-bridge.stream"):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass

    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    root.setLevel(target_level)

    return file_path
