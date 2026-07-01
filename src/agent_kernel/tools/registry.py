"""The tool registry: a single place that holds every callable the agent can use,
whether hand-written (M1) or discovered from an MCP server (M2). The agent loop
treats both identically.

Kept deliberately thin for M0 — the interface exists so M1 has a seam to plug
into, but no tools are registered yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..permissions import RiskLevel

# A handler takes parsed arguments and returns a JSON-serializable result.
ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    #: How risky the tool is, driving the permission policy (DESIGN.md §8).
    risk: RiskLevel = RiskLevel.READ
    #: Origin of the tool: "native" or the MCP server name it came from.
    source: str = "native"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        """Tool definitions in the shape providers expect (Anthropic `tools`)."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in self._tools.values()
        ]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name!r}")
        return await tool.handler(arguments)
