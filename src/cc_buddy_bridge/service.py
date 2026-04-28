"""Platform-specific auto-start service facade."""

from __future__ import annotations

import sys
from pathlib import Path

from .logging_setup import log_path as _project_log_path

LABEL = "com.github.cc-buddy-bridge.daemon"

if sys.platform == "darwin":
    from . import service_macos as _impl
elif sys.platform == "win32":
    from . import service_windows as _impl
else:
    _impl = None


def is_supported() -> bool:
    return _impl is not None


def service_kind() -> str:
    if _impl is None:
        return "unsupported"
    return _impl.SERVICE_KIND


def install_service() -> int:
    if _impl is None:
        print(
            "cc-buddy-bridge: service install is supported on macOS and Windows only.\n"
            "  Linux users: see issue #4 for the systemd variant.",
            file=sys.stderr,
        )
        return 2
    return _impl.install_service()


def uninstall_service() -> int:
    if _impl is None:
        print(
            "cc-buddy-bridge: service uninstall is supported on macOS and Windows only.\n"
            "  Linux users: see issue #4 for the systemd variant.",
            file=sys.stderr,
        )
        return 2
    return _impl.uninstall_service()


def is_installed() -> bool:
    return _impl.is_installed() if _impl is not None else False


def is_loaded() -> bool:
    return _impl.is_loaded() if _impl is not None else False


def definition_location() -> str | None:
    return _impl.definition_location() if _impl is not None else None


def log_path() -> Path:
    return _impl.log_path() if _impl is not None else _project_log_path()


def status_summary() -> str:
    if _impl is None:
        return "unsupported"
    return _impl.status_summary()
