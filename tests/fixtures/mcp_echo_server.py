"""A tiny but spec-compliant stdio MCP server, used to exercise the hand-rolled
client end-to-end without any external dependency.

Speaks JSON-RPC 2.0 over newline-delimited stdio: handles `initialize`, the
`notifications/initialized` notification, `tools/list`, and `tools/call`. Exposes
two read-only tools: `echo` and `add`. Standard library only.
"""

from __future__ import annotations

import json
import sys

TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the provided text.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "add",
        "description": "Add two numbers and return the sum.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
        "annotations": {"readOnlyHint": True},
    },
]


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def ok(request_id, result) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def err(request_id, code, message) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def handle(req: dict) -> None:
    method = req.get("method")
    request_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        ok(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "echo-mcp", "version": "0.1.0"},
            },
        )
    elif method == "notifications/initialized":
        pass  # notification: no response
    elif method == "tools/list":
        ok(request_id, {"tools": TOOLS})
    elif method == "tools/call":
        _call_tool(request_id, params.get("name"), params.get("arguments") or {})
    elif request_id is not None:
        err(request_id, -32601, f"Method not found: {method}")


def _call_tool(request_id, name, args) -> None:
    if name == "echo":
        ok(request_id, {"content": [{"type": "text", "text": str(args.get("text", ""))}], "isError": False})
    elif name == "add":
        try:
            total = args["a"] + args["b"]
            ok(request_id, {"content": [{"type": "text", "text": str(total)}], "isError": False})
        except Exception as exc:  # noqa: BLE001 - surface as a tool error
            ok(request_id, {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True})
    else:
        err(request_id, -32602, f"Unknown tool: {name}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle(req)


if __name__ == "__main__":
    main()
