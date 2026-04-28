from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from cc_buddy_bridge import service_windows


def test_task_command_prefers_pythonw_when_available(tmp_path: Path, monkeypatch):
    python = tmp_path / "python.exe"
    python.touch()
    pythonw = tmp_path / "pythonw.exe"
    pythonw.touch()
    monkeypatch.setattr(sys, "executable", str(python))

    expected = subprocess.list2cmdline([str(pythonw), "-m", "cc_buddy_bridge.cli", "daemon"])
    assert service_windows._task_command() == expected


def test_install_service_creates_onlogon_task(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(service_windows.shutil, "which", lambda _: "schtasks.exe")
    monkeypatch.setattr(service_windows, "_task_user", lambda: "alice")

    calls: list[list[str]] = []

    def fake_run(args: list[str], capture_output: bool, text: bool):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service_windows.subprocess, "run", fake_run)

    rc = service_windows.install_service()

    assert rc == 0
    assert calls == [[
        "schtasks",
        "/Create",
        "/SC",
        "ONLOGON",
        "/TN",
        service_windows.TASK_NAME,
        "/TR",
        service_windows._task_command(),
        "/RU",
        "alice",
        "/IT",
        "/NP",
        "/RL",
        "LIMITED",
        "/F",
    ]]
    out = capsys.readouterr().out
    assert "installed scheduled task" in out


def test_is_installed_checks_query(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(service_windows.shutil, "which", lambda _: "schtasks.exe")

    def fake_run(args: list[str], capture_output: bool, text: bool):
        assert args == ["schtasks", "/Query", "/TN", service_windows.TASK_NAME]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service_windows.subprocess, "run", fake_run)

    assert service_windows.is_installed() is True
