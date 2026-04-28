"""Unit tests for logging_setup.py — directory creation, rotation, idempotency."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import pytest

from cc_buddy_bridge import logging_setup


@pytest.fixture(autouse=True)
def _isolate_root_logger():
    """Snapshot/restore root logger so tests don't leak handlers."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


def test_project_root_resolves_to_repo_root():
    root = logging_setup.project_root()
    # Must contain pyproject.toml (proof we walked up to the repo root,
    # not stopped inside src/cc_buddy_bridge/).
    assert (root / "pyproject.toml").is_file()


def test_log_dir_default_under_project_root(monkeypatch):
    monkeypatch.delenv("CC_BUDDY_BRIDGE_LOG_DIR", raising=False)
    assert logging_setup.log_dir() == logging_setup.project_root() / "logs"


def test_log_dir_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_BUDDY_BRIDGE_LOG_DIR", str(tmp_path))
    assert logging_setup.log_dir() == tmp_path.resolve()


def test_log_path_filename(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_BUDDY_BRIDGE_LOG_DIR", str(tmp_path))
    assert logging_setup.log_path().name == logging_setup.LOG_FILE_NAME
    assert logging_setup.log_path().parent == tmp_path.resolve()


def test_setup_logging_creates_directory(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "logs"
    assert not target.exists()
    monkeypatch.setenv("CC_BUDDY_BRIDGE_LOG_DIR", str(target))

    returned = logging_setup.setup_logging("INFO")
    assert target.is_dir()
    assert returned == target.resolve() / logging_setup.LOG_FILE_NAME


def test_setup_logging_installs_rotating_handler(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_BUDDY_BRIDGE_LOG_DIR", str(tmp_path))
    logging_setup.setup_logging("DEBUG")

    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    fh = file_handlers[0]
    assert fh.maxBytes == logging_setup.MAX_BYTES
    assert fh.backupCount == logging_setup.BACKUP_COUNT
    assert fh.encoding == "utf-8"


def test_setup_logging_writes_a_record(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_BUDDY_BRIDGE_LOG_DIR", str(tmp_path))
    log_file = logging_setup.setup_logging("INFO")

    logging.getLogger("cc_buddy_bridge.test").info("hello-from-test")

    # Flush handlers so the file content is on disk.
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:  # noqa: BLE001
            pass

    contents = log_file.read_text(encoding="utf-8")
    assert "hello-from-test" in contents
    assert "cc_buddy_bridge.test" in contents


def test_setup_logging_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_BUDDY_BRIDGE_LOG_DIR", str(tmp_path))
    logging_setup.setup_logging("INFO")
    logging_setup.setup_logging("INFO")
    logging_setup.setup_logging("INFO")

    root = logging.getLogger()
    tagged = [
        h
        for h in root.handlers
        if getattr(h, "name", None) in ("cc-buddy-bridge.file", "cc-buddy-bridge.stream")
    ]
    # Exactly one of each kind, no matter how many times we call setup.
    assert sum(1 for h in tagged if h.name == "cc-buddy-bridge.file") == 1
    assert sum(1 for h in tagged if h.name == "cc-buddy-bridge.stream") == 1


def test_setup_logging_respects_level(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_BUDDY_BRIDGE_LOG_DIR", str(tmp_path))
    logging_setup.setup_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING


def test_setup_logging_unknown_level_falls_back_to_info(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_BUDDY_BRIDGE_LOG_DIR", str(tmp_path))
    logging_setup.setup_logging("NOT_A_REAL_LEVEL")
    assert logging.getLogger().level == logging.INFO


def test_tail_hint_platform_aware(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_BUDDY_BRIDGE_LOG_DIR", str(tmp_path))
    hint = logging_setup.tail_hint()
    # Whichever platform we're on, the path appears in the hint.
    assert str(logging_setup.log_path()) in hint
