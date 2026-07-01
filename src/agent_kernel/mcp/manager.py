"""Connects MCP servers and folds their tools into the kernel's `ToolRegistry`,
so the agent loop invokes them identically to native tools (DESIGN.md §4.1).

An MCP tool's handler simply proxies to `tools/call` on its client. Results that
the server flags as errors are raised, so the agent loop reports them as failed
tool calls just like a native tool that threw.

Risk: external tools are arbitrary, so they default to `EXEC` (which prompts
under the default policy). If the server hints a tool is read-only via the MCP
`annotations.readOnlyHint`, we honor that and mark it `READ`.
"""

from __future__ import annotations

from typing import Any

from ..permissions import RiskLevel
from ..tools.registry import Tool, ToolRegistry
from .client import MCPClient, content_to_text


class MCPManager:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._clients: dict[str, MCPClient] = {}

    async def connect_stdio(
        self,
        name: str,
        command: str,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        if name in self._clients:
            raise ValueError(f"An MCP server named {name!r} is already connected.")

        client = await MCPClient.connect_stdio(
            command, args, env=env, cwd=cwd, name=name
        )
        try:
            specs = await client.list_tools()
        except Exception:
            await client.close()
            raise

        registered: list[str] = []
        skipped: list[str] = []
        for spec in specs:
            tool = self._make_tool(client, spec)
            try:
                self._registry.register(tool)
                registered.append(tool.name)
            except ValueError:
                # Name already taken (e.g. by a native tool); skip it for M2.
                skipped.append(tool.name)

        self._clients[name] = client
        return {
            "server": name,
            "server_info": client.server_info,
            "protocol_version": client.protocol_version,
            "tools": registered,
            "skipped": skipped,
        }

    def _make_tool(self, client: MCPClient, spec: dict[str, Any]) -> Tool:
        name = spec["name"]
        read_only = bool((spec.get("annotations") or {}).get("readOnlyHint"))

        async def handler(arguments: dict[str, Any]) -> Any:
            result = await client.call_tool(name, arguments)
            text = content_to_text(result.get("content", []))
            if result.get("isError"):
                raise RuntimeError(text or "MCP tool reported an error")
            return text

        return Tool(
            name=name,
            description=spec.get("description", ""),
            input_schema=spec.get("inputSchema") or {"type": "object"},
            handler=handler,
            risk=RiskLevel.READ if read_only else RiskLevel.EXEC,
            source=client.name,
        )

    async def close_all(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
