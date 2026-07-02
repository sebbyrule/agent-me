"""Cancelling an in-flight turn: the client sends {"cancel": true} while the
provider is still streaming, and the kernel emits a `cancelled` event."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from agent_kernel.api import app as app_module
from agent_kernel.api.app import create_app
from agent_kernel.events import Event, MessageComplete, TextDelta
from agent_kernel.providers.base import Provider


class SlowProvider(Provider):
    name = "slow"

    async def stream(self, messages, *, tools=None, system=None) -> AsyncIterator[Event]:
        yield TextDelta(text="thinking...")
        await asyncio.sleep(30)  # hangs until the turn is cancelled
        yield MessageComplete(text="done")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(app_module, "create_provider", lambda config: SlowProvider())
    return TestClient(create_app())


def test_cancel_mid_stream(client):
    session_id = client.post("/session").json()["id"]
    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        ws.send_json({"input": "take your time"})
        first = ws.receive_json()
        assert first["type"] == "text_delta"

        ws.send_json({"cancel": True})
        nxt = ws.receive_json()
        assert nxt["type"] == "cancelled"


def test_can_start_a_new_turn_after_cancel(client):
    session_id = client.post("/session").json()["id"]
    with client.websocket_connect(f"/session/{session_id}/stream") as ws:
        ws.send_json({"input": "first"})
        assert ws.receive_json()["type"] == "text_delta"
        ws.send_json({"cancel": True})
        assert ws.receive_json()["type"] == "cancelled"

        # The socket is still usable for another turn.
        ws.send_json({"input": "second"})
        assert ws.receive_json()["type"] == "text_delta"
