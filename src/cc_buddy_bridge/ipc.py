"""IPC between hook scripts and the daemon.

Protocol: line-delimited JSON, one request → one response, then close.

Transport is pluggable via ``transport.make_transport``:
* macOS / Linux → Unix domain socket (``/tmp/cc-buddy-bridge.sock``)
* Windows      → TCP loopback (``127.0.0.1:48765``)

Request shapes (``evt`` field discriminates):
  {"evt":"session_start","session_id":"...","transcript_path":"...","cwd":"..."}
  {"evt":"session_end","session_id":"..."}
  {"evt":"turn_begin","session_id":"...","prompt":"..."}
  {"evt":"turn_end","session_id":"...","summary":"..."}
  {"evt":"pretooluse","session_id":"...","tool_use_id":"...","tool_name":"...","hint":"..."}  ← BLOCKS
  {"evt":"posttooluse","session_id":"...","tool_use_id":"..."}

Response shapes:
  {"ok":true}
  {"ok":true,"decision":"allow"|"deny"}  (for pretooluse)
  {"ok":false,"error":"..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Optional

from .transport import Transport, default_spec, make_transport

log = logging.getLogger(__name__)

# Kept for back-compat: imports like ``from .ipc import DEFAULT_SOCKET_PATH``
# in hud.py / cli.py keep working. On Windows this resolves to a TCP spec like
# ``127.0.0.1:48765``; on POSIX to ``/tmp/cc-buddy-bridge.sock``.
DEFAULT_SOCKET_PATH = default_spec()


# Handler signature: async (request_dict) -> response_dict.
Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class IPCServer:
    """Listens on a transport, dispatches one request per connection.

    ``socket_path`` is a transport spec (path or ``host:port``). Name kept for
    back-compat; ``Daemon`` passes it through unmodified.
    """

    def __init__(self, handler: Handler, socket_path: Optional[str] = None) -> None:
        self.handler = handler
        self._transport: Transport = make_transport(socket_path)
        self._server: asyncio.AbstractServer | None = None

    @property
    def address(self) -> str:
        """Transport-specific address string for logs / errors."""
        return self._transport.address

    # Back-compat alias: existing callers / tests may still read .socket_path.
    @property
    def socket_path(self) -> str:
        return self._transport.address

    async def start(self) -> None:
        self._server = await self._transport.start_server(self._on_conn)
        log.info("ipc listening at %s", self._transport.address)

    async def serve_forever(self) -> None:
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        self._transport.cleanup_stale()

    async def _on_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line:
                return
            try:
                req = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                await self._reply(writer, {"ok": False, "error": f"bad json: {e}"})
                return
            try:
                resp = await self.handler(req)
            except Exception as e:  # noqa: BLE001 — handler faults shouldn't kill the server
                log.exception("handler error for req=%r", req)
                resp = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            await self._reply(writer, resp)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    async def _reply(writer: asyncio.StreamWriter, obj: dict[str, Any]) -> None:
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        writer.write(data)
        await writer.drain()
