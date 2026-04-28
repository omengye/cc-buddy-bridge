# Windows 11 Manual Validation Runbook

This runbook is the final Phase 6 acceptance pass for the Windows port.

Use it on a real Windows 11 machine (preferred) or a VM with BLE hardware
pass-through and a working Claude Code installation.

## Goal

Verify that the Windows build works end-to-end:

- local IPC uses TCP loopback
- hooks can invoke the bridge from a path that may contain spaces
- the daemon can talk to the buddy over BLE
- project-local logging works
- `install --service` creates a working Task Scheduler entry
- `status`, `hud`, `install`, and `uninstall` behave sensibly

## Preconditions

- Windows 11
- Python 3.11+
- Claude Code installed and working
- A flashed `claude-desktop-buddy` device available for pairing
- Bluetooth enabled
- PowerShell available

## 1. Fresh checkout + test pass

```powershell
git clone https://github.com/SnowWarri0r/cc-buddy-bridge
cd cc-buddy-bridge
py -3.12 -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python.exe -m pytest -q
```

### Expected

- tests pass
- no install-time traceback

## 2. Confirm project-local logging

```powershell
.venv\Scripts\cc-buddy-bridge.exe daemon
```

In a second PowerShell window:

```powershell
Get-ChildItem .\logs
Get-Content .\logs\cc-buddy-bridge.log -Wait
```

### Expected

- `logs\cc-buddy-bridge.log` exists
- the daemon writes startup logs there
- no attempt is made to write to `~/Library/Logs` or another macOS-only path

## 3. Confirm Windows IPC transport

With the daemon still running:

```powershell
.venv\Scripts\cc-buddy-bridge.exe hud --ascii
```

### Expected

- command returns promptly
- if daemon is reachable, output is a one-line status summary
- if stick is disconnected, HUD still talks to daemon and shows an "off" / empty-like state instead of a socket-path crash
- daemon is listening on TCP loopback (`127.0.0.1:48765` by default)

## 4. Install Claude hooks

```powershell
.venv\Scripts\cc-buddy-bridge.exe install
.venv\Scripts\cc-buddy-bridge.exe status
```

### Expected

- `~/.claude/settings.json` is updated and backed up
- `status` shows installed hook commands
- hook commands point at the venv executable
- commands still work if the repo path contains spaces

## 5. Real Claude Code session check

Start a real Claude Code session and trigger:

1. a normal prompt
2. a tool-use event (for example a harmless shell command)
3. a turn completion

### Expected

- buddy state changes as Claude becomes active / idle
- permission prompts appear on the stick when expected
- allow / deny round-trip still works
- assistant completion causes the configured stick-side celebration behavior
- Windows notifier path produces an audible system chime
- daemon log records the events without traceback

## 6. Install auto-start service

```powershell
.venv\Scripts\cc-buddy-bridge.exe install --service
schtasks /Query /TN "com.github.cc-buddy-bridge.daemon"
.venv\Scripts\cc-buddy-bridge.exe status
```

### Expected

- install succeeds
- Task Scheduler contains `com.github.cc-buddy-bridge.daemon`
- `status` reports the Windows Task Scheduler backend
- status prints the project log path

## 7. Logoff/logon validation

After `install --service`, sign out and sign back in.

Then run:

```powershell
Get-Content .\logs\cc-buddy-bridge.log -Tail 50
.venv\Scripts\cc-buddy-bridge.exe status
```

### Expected

- daemon starts at logon without manual launch
- fresh log entries appear after logon
- no console window is required for steady-state operation

## 8. Negative checks

### 8.1 Duplicate daemon guard

While the service or one daemon instance is already running:

```powershell
.venv\Scripts\cc-buddy-bridge.exe daemon
```

### Expected

- command refuses to start a second daemon
- message references the existing transport address

### 8.2 Service uninstall

```powershell
.venv\Scripts\cc-buddy-bridge.exe uninstall --service
schtasks /Query /TN "com.github.cc-buddy-bridge.daemon"
```

### Expected

- uninstall succeeds
- `schtasks /Query` fails because the task is gone

### 8.3 Hook uninstall

```powershell
.venv\Scripts\cc-buddy-bridge.exe uninstall
.venv\Scripts\cc-buddy-bridge.exe status
```

### Expected

- hooks are removed cleanly
- unrelated user hooks remain untouched
- `status` no longer shows cc-buddy-bridge hook registrations

## 9. Evidence to capture

Capture at least these artifacts for final acceptance / PR notes:

1. `pytest -q` success on Windows
2. `cc-buddy-bridge status` showing Windows service backend
3. `schtasks /Query /TN "com.github.cc-buddy-bridge.daemon"`
4. a snippet of `logs\cc-buddy-bridge.log`
5. one real-session screenshot or terminal snippet showing hook-triggered behavior

## 10. Common failure signatures

### Hook command fails only when path contains spaces

Likely cause: command quoting regression. Re-check `~/.claude/settings.json` hook command strings.

### `hud` / hook commands cannot reach daemon

Likely cause: loopback port conflict or daemon not running. Check `127.0.0.1:48765`, daemon logs, and duplicate-daemon guard output.

### Service installs but does not start on logon

Check Task Scheduler task details, current user context, and whether `pythonw.exe` exists next to the active interpreter.

### No sound on turn completion

Check whether Windows system sounds are enabled; the bridge only uses `winsound.MessageBeep`, not toast notifications.

## Acceptance summary

The Windows port is ready when all sections above pass without code changes.
