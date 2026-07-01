"""Hand-rolled MCP client (DESIGN.md §6) — M2.

Written from scratch (the official SDK is reference only, principle #4). Speaks
JSON-RPC 2.0 over a stdio transport to a child MCP server process:

- newline-delimited JSON framing (one message per line)
- request/response correlation by id, via a background reader task
- the initialize -> initialized handshake
- tools/list discovery and tools/call invocation
- timeouts and tolerance of malformed/unsolicited messages (DESIGN.md §6)

Scope is deliberately "one well-behaved server, end-to-end" (§9); HTTP+SSE
transport and richer capabilities can come later without changing this shape.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .. import __version__

#: The MCP protocol revision we advertise. Servers negotiate and may reply with
#: a different supported version; we proceed with whatever they return.
PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    """A JSON-RPC error from the server, or a transport-level failure."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def content_to_text(content: list[dict[str, Any]]) -> str:
    """Flatten MCP tool-result content blocks into a single string."""
    parts: list[str] = []
    for block in content or []:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        else:
            parts.append(json.dumps(block))
    return "\n".join(parts)


class MCPClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.server_info: dict[str, Any] = {}
        self.protocol_version: str | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._id = 0
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr: list[str] = []

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    async def connect_stdio(
        cls,
        command: str,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        name: str | None = None,
        timeout: float = 30.0,
    ) -> "MCPClient":
        proc = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
        self = cls(name or command)
        self._proc = proc
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            await self._initialize(timeout)
        except Exception:
            await self.close()
            raise
        return self

    async def _initialize(self, timeout: float) -> None:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agent-me", "version": __version__},
            },
            timeout=timeout,
        )
        self.server_info = result.get("serverInfo", {})
        self.protocol_version = result.get("protocolVersion")
        # Per the spec, follow the initialize response with this notification.
        await self._notify("notifications/initialized")

    async def close(self) -> None:
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(MCPError("connection closed"))
        self._pending.clear()
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()

    # -- protocol ----------------------------------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._request("tools/list")
        return result.get("tools", [])

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, timeout: float = 60.0
    ) -> dict[str, Any]:
        return await self._request(
            "tools/call", {"name": name, "arguments": arguments}, timeout=timeout
        )

    # -- transport ---------------------------------------------------------

    async def _request(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 30.0
    ) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None:
            raise MCPError("client is not connected")
        self._id += 1
        request_id = self._id
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = future
        await self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        )
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise MCPError(f"timed out after {timeout}s waiting for '{method}'") from exc

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def _write(self, payload: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write((json.dumps(payload) + "\n").encode())
        await self._proc.stdin.drain()

    async def _reader_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:  # EOF: the server exited
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(MCPError("server closed the connection"))
                self._pending.clear()
                return
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                continue  # tolerate noise on stdout
            message_id = message.get("id")
            if message_id in self._pending:
                future = self._pending.pop(message_id)
                if future.done():
                    continue
                if "error" in message:
                    err = message["error"]
                    future.set_exception(
                        MCPError(err.get("message", "MCP error"), err.get("code"))
                    )
                else:
                    future.set_result(message.get("result", {}))
            # Unsolicited notifications / server->client requests: ignored in M2.

    async def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                return
            self._stderr.append(line.decode(errors="replace").rstrip())
