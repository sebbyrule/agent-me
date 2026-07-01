"""The interactive REPL (DESIGN.md §4.2).

Connects to the kernel's WebSocket, forwards user input, and renders the
normalized event stream (`text_delta`, `message_complete`, `error`, and — from
M1 — tool-call events) as it arrives. Supports attaching to an existing session
so the kernel can keep running independently of any one client.
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx
import websockets


class ReplClient:
    def __init__(self, host: str, port: int) -> None:
        self._base_http = f"http://{host}:{port}"
        self._base_ws = f"ws://{host}:{port}"

    async def _create_session(self) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._base_http}/session")
            resp.raise_for_status()
            return resp.json()["id"]

    async def run(self, session_id: str | None = None) -> None:
        try:
            if session_id is None:
                session_id = await self._create_session()
        except httpx.HTTPError as exc:
            print(f"Could not reach the kernel at {self._base_http}: {exc}")
            print("Is `agent-kernel` running?")
            return

        url = f"{self._base_ws}/session/{session_id}/stream"
        print(f"Connected to session {session_id}. Type your message; Ctrl-D to exit.\n")

        async with websockets.connect(url) as ws:
            while True:
                try:
                    user_input = await asyncio.to_thread(input, "you › ")
                except EOFError:
                    print("\nbye")
                    return
                if not user_input.strip():
                    continue

                await ws.send(_json_dumps({"input": user_input}))
                await self._render_turn(ws)

    async def _render_turn(self, ws: "websockets.WebSocketClientProtocol") -> None:
        import json

        printed_prefix = False
        async for raw in ws:
            event = json.loads(raw)
            etype = event.get("type")
            if etype == "text_delta":
                if not printed_prefix:
                    sys.stdout.write("bot › ")
                    printed_prefix = True
                sys.stdout.write(event["text"])
                sys.stdout.flush()
            elif etype == "message_complete":
                sys.stdout.write("\n\n")
                sys.stdout.flush()
                return
            elif etype == "error":
                sys.stdout.write(f"\n[error] {event['message']}\n\n")
                sys.stdout.flush()
                return


def _json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj)


def run() -> None:
    host = os.getenv("KERNEL_HOST", "127.0.0.1")
    port = int(os.getenv("KERNEL_PORT", "8765"))
    session_id = os.getenv("AGENT_SESSION_ID")  # attach to an existing session
    asyncio.run(ReplClient(host, port).run(session_id))
