"""The kernel's MCP server, verified by connecting our own MCP client to it —
a full protocol round-trip (initialize -> tools/list -> tools/call)."""

from __future__ import annotations

import os
import sys

import pytest
import pytest_asyncio

from agent_kernel.mcp.client import MCPClient, content_to_text

SERVER_CMD = [sys.executable, "-m", "agent_kernel.mcp.server"]


@pytest_asyncio.fixture
async def client():
    c = await MCPClient.connect_stdio(SERVER_CMD[0], SERVER_CMD[1:], name="agent-me")
    try:
        yield c
    finally:
        await c.close()


async def test_handshake(client):
    assert client.server_info.get("name") == "agent-me"


async def test_exposes_read_tools_only_by_default(client):
    tools = {t["name"] for t in await client.list_tools()}
    assert {"read_file", "list_dir"} <= tools
    # write/exec tools are withheld from external clients by default.
    assert "write_file" not in tools
    assert "run_shell" not in tools


async def test_call_list_dir(client):
    result = await client.call_tool("list_dir", {"path": "."})
    assert result["isError"] is False
    # The repo root has a pyproject.toml.
    assert "pyproject.toml" in content_to_text(result["content"])


async def test_call_read_file(client, tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("hello mcp server", encoding="utf-8")
    result = await client.call_tool("read_file", {"path": str(target)})
    assert content_to_text(result["content"]) == "hello mcp server"


async def test_expose_all_env_reveals_write_and_exec():
    env = {**os.environ, "AGENT_MCP_EXPOSE_ALL": "1"}
    c = await MCPClient.connect_stdio(
        SERVER_CMD[0], SERVER_CMD[1:], env=env, name="agent-me-full"
    )
    try:
        tools = {t["name"] for t in await c.list_tools()}
        assert {"read_file", "list_dir", "write_file", "run_shell"} <= tools
    finally:
        await c.close()


async def test_unknown_tool_reports_error(client):
    result = await client.call_tool("does_not_exist", {})
    assert result["isError"] is True
