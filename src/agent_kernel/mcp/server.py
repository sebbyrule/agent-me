"""Hand-rolled MCP server (DESIGN.md §6/§7) — M5.

The mirror image of the M2 client: exposes the kernel's own native tools to
*other* MCP clients (Claude Desktop, another agent, or our own client) over a
stdio JSON-RPC transport. Written from scratch, same protocol as the client.

Run it standalone:

    python -m agent_kernel.mcp.server        # (or the `agent-mcp-server` script)

Safety: external clients are arbitrary, so by default only read-risk tools are
exposed (read_file, list_dir). Set AGENT_MCP_EXPOSE_ALL=1 to also expose the
write/exec tools — do that only for trusted clients (DESIGN.md §8).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, TextIO

from .. import __version__
from ..permissions import RiskLevel
from ..providers.base import stringify_tool_result
from ..tools import register_native_tools
from ..tools.registry import Tool, ToolRegistry
from .client import PROTOCOL_VERSION

SERVER_INFO = {"name": "agent-me", "version": __version__}


def build_registry(
    expose_all: bool = False, workspace: str | None = None
) -> ToolRegistry:
    """Registry of the tools this server exposes. Read-only unless `expose_all`;
    file/shell tools are sandboxed to `workspace` (default the CWD)."""
    full = ToolRegistry()
    register_native_tools(full, workspace)
    if expose_all:
        return full
    exposed = ToolRegistry()
    for tool in full.list():
        if tool.risk == RiskLevel.READ:
            exposed.register(tool)
    return exposed


def _tool_spec(tool: Tool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.input_schema,
        "annotations": {"readOnlyHint": tool.risk == RiskLevel.READ},
    }


def _result(request_id: Any, content_text: str, is_error: bool) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [{"type": "text", "text": content_text}],
            "isError": is_error,
        },
    }


async def handle(registry: ToolRegistry, req: dict[str, Any]) -> dict[str, Any] | None:
    """Produce a JSON-RPC response for one request (or None for a notification)."""
    method = req.get("method")
    request_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": [_tool_spec(t) for t in registry.list()]},
        }
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if registry.get(name) is None:
            return _result(request_id, f"Unknown tool: {name}", True)
        try:
            result = await registry.invoke(name, arguments)
            return _result(request_id, stringify_tool_result(result), False)
        except Exception as exc:  # tool failure -> MCP isError
            return _result(request_id, f"{type(exc).__name__}: {exc}", True)
    if request_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return None


async def serve(
    registry: ToolRegistry,
    in_stream: TextIO | None = None,
    out_stream: TextIO | None = None,
) -> None:
    """Read newline-delimited JSON-RPC from stdin and reply on stdout.

    stdin is read in a worker thread so this works uniformly across platforms
    (asyncio can't poll a stdin pipe directly on Windows).
    """
    in_stream = in_stream or sys.stdin
    out_stream = out_stream or sys.stdout
    while True:
        line = await asyncio.to_thread(in_stream.readline)
        if not line:  # EOF: the client closed the connection
            return
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = await handle(registry, req)
        if response is not None:
            out_stream.write(json.dumps(response) + "\n")
            out_stream.flush()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    expose_all = os.getenv("AGENT_MCP_EXPOSE_ALL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    registry = build_registry(
        expose_all=expose_all, workspace=os.getenv("WORKSPACE_DIR")
    )
    asyncio.run(serve(registry))


if __name__ == "__main__":
    main()
