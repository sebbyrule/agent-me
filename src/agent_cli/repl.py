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
            elif etype == "tool_call_start":
                printed_prefix = False
                args = json.dumps(event.get("arguments", {}))
                sys.stdout.write(f"\n  ⚙ {event['name']}({args})\n")
                sys.stdout.flush()
            elif etype == "tool_call_result":
                mark = "✗" if event.get("is_error") else "→"
                sys.stdout.write(f"  {mark} {_short(event.get('result'))}\n")
                sys.stdout.flush()
            elif etype == "permission_request":
                approved = await self._prompt_permission(event)
                await ws.send(
                    _json_dumps({"id": event["id"], "approved": approved})
                )
            elif etype == "message_complete":
                # One provider call finished; more tool rounds may follow.
                sys.stdout.write("\n")
                sys.stdout.flush()
            elif etype == "turn_complete":
                sys.stdout.write("\n")
                sys.stdout.flush()
                return
            elif etype == "error":
                sys.stdout.write(f"\n[error] {event['message']}\n\n")
                sys.stdout.flush()
                return

    async def _prompt_permission(self, event: dict) -> bool:
        args = _json_dumps(event.get("arguments", {}))
        prompt = (
            f"\n  ⚠ allow {event['risk']} tool '{event['name']}'({args})? [y/N] "
        )
        answer = await asyncio.to_thread(input, prompt)
        return answer.strip().lower() in ("y", "yes")


def _json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj)


def _short(result, limit: int = 300) -> str:
    """One-line, truncated rendering of a tool result for the REPL."""
    import json

    text = result if isinstance(result, str) else json.dumps(result, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"


def run() -> None:
    host = os.getenv("KERNEL_HOST", "127.0.0.1")
    port = int(os.getenv("KERNEL_PORT", "8765"))
    session_id = os.getenv("AGENT_SESSION_ID")  # attach to an existing session
    asyncio.run(ReplClient(host, port).run(session_id))
