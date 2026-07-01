"""MCP tools, once connected, must behave exactly like native tools: appear in
the registry and be invokable by the agent loop. This drives that end-to-end
with the fixture server and a scripted provider."""

from __future__ import annotations

import os
import sys
from typing import Any, AsyncIterator

import pytest_asyncio

from agent_kernel.agent.loop import AgentLoop
from agent_kernel.events import (
    Event,
    MessageComplete,
    ToolCallResult,
    ToolCallStart,
)
from agent_kernel.mcp.manager import MCPManager
from agent_kernel.permissions import PermissionPolicy, RiskLevel
from agent_kernel.providers.base import Provider
from agent_kernel.session.store import SessionStore
from agent_kernel.tools import register_native_tools
from agent_kernel.tools.registry import ToolRegistry

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mcp_echo_server.py")


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, scripts: list[list[Event]]) -> None:
        self._scripts = list(scripts)

    async def stream(self, messages, *, tools=None, system=None) -> AsyncIterator[Event]:
        for event in self._scripts.pop(0):
            yield event


@pytest_asyncio.fixture
async def registry_with_mcp():
    registry = ToolRegistry()
    register_native_tools(registry)
    manager = MCPManager(registry)
    summary = await manager.connect_stdio("echo", sys.executable, [FIXTURE])
    try:
        yield registry, manager, summary
    finally:
        await manager.close_all()


async def test_connect_registers_tools_with_source_and_risk(registry_with_mcp):
    registry, _manager, summary = registry_with_mcp
    assert set(summary["tools"]) == {"echo", "add"}
    assert summary["server_info"]["name"] == "echo-mcp"

    echo = registry.get("echo")
    assert echo is not None
    assert echo.source == "echo"
    # readOnlyHint in the fixture -> READ risk.
    assert echo.risk == RiskLevel.READ


async def test_registry_invokes_mcp_tool(registry_with_mcp):
    registry, _manager, _summary = registry_with_mcp
    result = await registry.invoke("add", {"a": 2, "b": 3})
    assert result == "5"


async def test_agent_loop_uses_mcp_tool_end_to_end(registry_with_mcp, tmp_path):
    registry, _manager, _summary = registry_with_mcp
    store = SessionStore(tmp_path)
    session = store.create()

    provider = ScriptedProvider(
        [
            [
                ToolCallStart(id="c1", name="add", arguments={"a": 20, "b": 22}),
                MessageComplete(text="", stop_reason="tool_use"),
            ],
            [MessageComplete(text="The sum is 42.", stop_reason="end_turn")],
        ]
    )
    loop = AgentLoop(provider, store, registry, policy=PermissionPolicy("allow"))

    events = [e async for e in loop.run_turn(session, "add 20 and 22")]
    result = next(e for e in events if isinstance(e, ToolCallResult))
    assert result.name == "add"
    assert result.result == "42"
    assert not result.is_error
