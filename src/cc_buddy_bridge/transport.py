"""Cross-platform IPC transport abstraction.

The daemon and hook scripts originally talked over a Unix domain socket on
``/tmp/cc-buddy-bridge.sock``. That doesn't work on Windows (Python's asyncio
has no ``start_unix_server`` on Win32 even though Win10 1803+ has AF_UNIX),
so we abstract the channel:

* Unix / macOS  → ``UnixTransport``  (path, ``asyncio.start_unix_server``)
* Windows       → ``TcpLoopbackTransport``  (``127.0.0.1:<port>``,
  ``asyncio.start_server``)

The factory ``make_transport(spec)`` resolves the actual transport from one of:

1. An explicit *spec* string (CLI ``--socket`` flag).
2. The ``CC_BUDDY_BRIDGE_SOCK`` env var (legacy name kept for back-compat).
3. The platform default.

Spec syntax
-----------
* ``"127.0.0.1:48765"`` or ``":48765"`` → TCP loopback on the given port.
* Anything else → file path → Unix socket. **On Windows this fails fast**
  rather than silently degrading, so users get a clear error.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol

log = logging.getLogger(__name__)


# Platform defaults.
DEFAULT_UNIX_PATH = "/tmp/cc-buddy-bridge.sock"
DEFAULT_TCP_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 48765  # 0xBE6D — no IANA registration conflict


# Connection callback for the asyncio server. Same shape as
# ``asyncio.start_unix_server``'s and ``asyncio.start_server``'s callback.
ConnHandler = Callable[[Any, Any], Awaitable[None]]


class Transport(Protocol):
    """Abstract IPC channel. Both async (server) and sync (client) sides."""

    @property
    def address(self) -> str:
        """Human-readable address for logs / CLI hints."""
        ...

    async def start_server(self, on_conn: ConnHandler) -> Any:
        """Start an asyncio server bound to this transport. Returns ``AbstractServer``."""
        ...

    def sync_connect(self, timeout: float) -> socket.socket:
        """Open a *blocking* client socket. Used by hook subprocesses."""
        ...

    def is_in_use(self) -> bool:
        """True iff some other process is actively accepting on this address."""
        ...

    def cleanup_stale(self) -> None:
        """Remove leftover artifacts (Unix socket file). No-op for TCP."""
        ...


# ---------------------------------------------------------------------------
# Unix socket implementation (macOS / Linux)
# ---------------------------------------------------------------------------


class UnixTransport:
    """AF_UNIX SOCK_STREAM transport. Not available on Windows."""

    def __init__(self, path: str) -> None:
        if sys.platform == "win32":
            raise RuntimeError(
                "UnixTransport is not supported on Windows. "
                "Use a TCP spec like '127.0.0.1:48765' instead."
            )
        self.path = path

    @property
    def address(self) -> str:
        return self.path

    async def start_server(self, on_conn: ConnHandler) -> Any:
        # Lazy-import to keep the module importable on Windows.
        import asyncio

        # Remove any stale socket file from a previous run.
        p = Path(self.path)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
        server = await asyncio.start_unix_server(on_conn, path=self.path)
        try:
            os.chmod(self.path, 0o600)  # user-only
        except OSError:
            # File systems without POSIX perms (rare on macOS/Linux) — ignore.
            pass
        return server

    def sync_connect(self, timeout: float) -> socket.socket:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(self.path)
        return s

    def is_in_use(self) -> bool:
        if not os.path.exists(self.path):
            return False
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(self.path)
        except (ConnectionRefusedError, FileNotFoundError):
            # Stale socket file — caller will treat as not-in-use.
            self.cleanup_stale()
            return False
        except OSError:
            # Permissions / unreadable — be conservative.
            return True
        else:
            return True
        finally:
            try:
                s.close()
            except OSError:
                pass

    def cleanup_stale(self) -> None:
        try:
            if os.path.exists(self.path):
                os.unlink(self.path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# TCP loopback implementation (Windows; usable everywhere as fallback)
# ---------------------------------------------------------------------------


class TcpLoopbackTransport:
    """AF_INET SOCK_STREAM bound to 127.0.0.1.

    Loopback-only: the server refuses connections from non-localhost peers
    because asyncio binds to ``host`` literally and 127.0.0.1 is unreachable
    from off-box.
    """

    def __init__(self, host: str = DEFAULT_TCP_HOST, port: int = DEFAULT_TCP_PORT) -> None:
        if not host:
            host = DEFAULT_TCP_HOST
        self.host = host
        self.port = int(port)

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    async def start_server(self, on_conn: ConnHandler) -> Any:
        import asyncio

        return await asyncio.start_server(on_conn, host=self.host, port=self.port)

    def sync_connect(self, timeout: float) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((self.host, self.port))
        return s

    def is_in_use(self) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect((self.host, self.port))
        except (ConnectionRefusedError, OSError):
            return False
        else:
            return True
        finally:
            try:
                s.close()
            except OSError:
                pass

    def cleanup_stale(self) -> None:
        # No filesystem artifact for TCP. No-op.
        return None


# ---------------------------------------------------------------------------
# Spec parsing + factory
# ---------------------------------------------------------------------------


def parse_spec(spec: str) -> Transport:
    """Parse a transport spec string.

    Rules:

    * Empty / None → caller's problem; use ``make_transport`` instead.
    * Contains ``:`` and the right-hand side parses as an int → TCP.
      Host may be empty (``:48765`` → ``127.0.0.1:48765``).
    * Otherwise → Unix socket path.

    On Windows, a path-shaped spec raises ``ValueError`` to fail fast.
    """
    if spec is None or spec == "":
        raise ValueError("transport spec must be non-empty")

    # TCP form: "host:port" or ":port"
    # Be careful: Windows paths like "C:\\foo" also contain ':'. We disambiguate
    # by requiring the segment after the *last* ':' to parse as an int AND
    # the host segment to be a valid IP/hostname character set (no backslash,
    # no drive letter pattern).
    if ":" in spec:
        host, sep, port_s = spec.rpartition(":")
        # Drive-letter heuristic: "C:foo" or "C:\\foo" → path
        is_drive_letter = (
            len(host) == 1
            and host.isalpha()
            and (port_s.startswith("\\") or port_s.startswith("/"))
        )
        if not is_drive_letter and port_s.isdigit() and "\\" not in spec and "/" not in host:
            try:
                port = int(port_s)
            except ValueError:
                pass
            else:
                if not (0 < port < 65536):
                    raise ValueError(f"port out of range: {port}")
                return TcpLoopbackTransport(host=host or DEFAULT_TCP_HOST, port=port)

    # Path form.
    if sys.platform == "win32":
        raise ValueError(
            f"Unix socket paths are not supported on Windows: {spec!r}. "
            f"Use a TCP spec like '127.0.0.1:{DEFAULT_TCP_PORT}' or ':{DEFAULT_TCP_PORT}'."
        )
    return UnixTransport(path=spec)


def default_spec() -> str:
    """Platform-appropriate default spec string."""
    if sys.platform == "win32":
        return f"{DEFAULT_TCP_HOST}:{DEFAULT_TCP_PORT}"
    return DEFAULT_UNIX_PATH


def make_transport(spec: Optional[str] = None) -> Transport:
    """Resolve a Transport from CLI/env/platform-default.

    Precedence (high → low):
      1. ``spec`` argument (e.g. CLI ``--socket``)
      2. ``CC_BUDDY_BRIDGE_SOCK`` env var
      3. Platform default
    """
    chosen = spec or os.environ.get("CC_BUDDY_BRIDGE_SOCK") or default_spec()
    return parse_spec(chosen)
