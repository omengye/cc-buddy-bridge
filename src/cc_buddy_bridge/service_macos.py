"""macOS launchd agent install/uninstall."""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from .logging_setup import log_path as _project_log_path

LABEL = "com.github.cc-buddy-bridge.daemon"
SERVICE_KIND = "macOS launchd"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = _project_log_path()


def log_path() -> Path:
    return _project_log_path()


def definition_location() -> str:
    return str(PLIST_PATH)


def _build_plist() -> bytes:
    """Render the plist as XML bytes."""
    current_log_path = log_path()
    plist = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "cc_buddy_bridge.cli", "daemon"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "StandardOutPath": str(current_log_path),
        "StandardErrorPath": str(current_log_path),
        "EnvironmentVariables": {
            "HOME": str(Path.home()),
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
    }
    return plistlib.dumps(plist)


def install_service() -> int:
    if sys.platform != "darwin":
        print(
            "cc-buddy-bridge: service install is macOS-only for this backend.",
            file=sys.stderr,
        )
        return 2

    if shutil.which("launchctl") is None:
        print("cc-buddy-bridge: `launchctl` not found on PATH", file=sys.stderr)
        return 2

    current_log_path = log_path()
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    current_log_path.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_bytes(_build_plist())

    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    result = subprocess.run(
        ["launchctl", "load", "-w", str(PLIST_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"launchctl load failed ({result.returncode}): {result.stderr.strip()}",
            file=sys.stderr,
        )
        return 2

    print(f"installed: {PLIST_PATH}")
    print(f"logs at:   {current_log_path}")
    print("daemon will start on your next login (and is starting now).")
    return 0


def uninstall_service() -> int:
    if sys.platform != "darwin":
        print("cc-buddy-bridge: service uninstall is macOS-only for this backend", file=sys.stderr)
        return 2

    if not PLIST_PATH.exists():
        print("service not installed; nothing to do")
        return 0

    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    PLIST_PATH.unlink()
    print(f"removed: {PLIST_PATH}")
    return 0


def is_installed() -> bool:
    return sys.platform == "darwin" and PLIST_PATH.exists()


def is_loaded() -> bool:
    if sys.platform != "darwin" or shutil.which("launchctl") is None:
        return False
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    return any(LABEL in line for line in result.stdout.splitlines())


def status_summary() -> str:
    return "loaded" if is_loaded() else "installed but not loaded"
