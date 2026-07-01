"""Exercises the hand-rolled MCP client against the real (minimal) stdio server
fixture: full handshake, discovery, invocation, and error handling."""

from __future__ import annotations

import os
import sys

import pytest
import pytest_asyncio

from agent_kernel.mcp.client import MCPClient, MCPError, content_to_text

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mcp_echo_server.py")


@pytest_asyncio.fixture
async def client():
    c = await MCPClient.connect_stdio(sys.executable, [FIXTURE], name="echo")
    try:
        yield c
    finally:
        await c.close()


async def test_handshake_populates_server_info(client):
    assert client.server_info.get("name") == "echo-mcp"
    assert client.protocol_version  # negotiated during initialize


async def test_list_tools_discovers_fixture_tools(client):
    tools = await client.list_tools()
    names = {t["name"] for t in tools}
    assert {"echo", "add"} <= names


async def test_call_echo(client):
    result = await client.call_tool("echo", {"text": "hi there"})
    assert result["isError"] is False
    assert content_to_text(result["content"]) == "hi there"


async def test_call_add(client):
    result = await client.call_tool("add", {"a": 21, "b": 21})
    assert content_to_text(result["content"]) == "42"


async def test_unknown_tool_raises(client):
    with pytest.raises(MCPError):
        await client.call_tool("nope", {})


def test_content_to_text_mixed_blocks():
    text = content_to_text([{"type": "text", "text": "a"}, {"type": "image", "data": "x"}])
    assert text.startswith("a\n")
