"""End-to-end test of the kernel's WebSocket contract with a fake provider
injected, so the turn/tool/permission wiring in the API layer is exercised for
real (not just the loop in isolation)."""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest
from fastapi.testclient import TestClient

from agent_kernel.api import app as app_module
from agent_kernel.api.app import create_app
from agent_kernel.events import MessageComplete, ToolCallStart
from agent_kernel.providers.base import Provider


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, scripts: list[list]) -> None:
        self._scripts = list(scripts)

    async def stream(self, messages, *, tools=None, system=None) -> AsyncIterator:
        for event in self._scripts.pop(0):
            yield event


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("AGENT_TOOL_POLICY", "ask")
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))  # native tools sandbox here
    return TestClient(create_app())


def test_write_tool_turn_with_permission(client, tmp_path, monkeypatch):
    target = tmp_path / "out.txt"
    provider = ScriptedProvider(
        [
            [
                ToolCallStart(
                    id="c1",
                    name="write_file",
                    arguments={"path": str(target), "content": "written!"},
                ),
                MessageComplete(text="", stop_reason="tool_use"),
            ],
            [MessageComplete(text="Saved it.", stop_reason="end_turn")],
        ]
    )
    monkeypatch.setattr(app_module, "create_provider", lambda config: provider)

    session_id = client.post("/session").json()["id"]
    seen: list[str] = []
    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        ws.send_json({"input": "please write the file"})
        while True:
            event = ws.receive_json()
            seen.append(event["type"])
            if event["type"] == "permission_request":
                assert event["risk"] == "write"
                ws.send_json({"id": event["id"], "approved": True})
            if event["type"] in ("turn_complete", "error"):
                break

    assert "tool_call_start" in seen
    assert "permission_request" in seen
    assert "tool_call_result" in seen
    assert seen[-1] == "turn_complete"
    assert target.read_text(encoding="utf-8") == "written!"


def test_denied_permission_does_not_write(client, tmp_path, monkeypatch):
    target = tmp_path / "nope.txt"
    provider = ScriptedProvider(
        [
            [
                ToolCallStart(
                    id="c1",
                    name="write_file",
                    arguments={"path": str(target), "content": "x"},
                ),
                MessageComplete(text="", stop_reason="tool_use"),
            ],
            [MessageComplete(text="Okay, skipped.", stop_reason="end_turn")],
        ]
    )
    monkeypatch.setattr(app_module, "create_provider", lambda config: provider)

    session_id = client.post("/session").json()["id"]
    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        ws.send_json({"input": "write it"})
        while True:
            event = ws.receive_json()
            if event["type"] == "permission_request":
                ws.send_json({"id": event["id"], "approved": False})
            if event["type"] in ("turn_complete", "error"):
                break

    assert not target.exists()
