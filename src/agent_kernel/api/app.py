"""FastAPI app exposing the kernel's HTTP/WS surface (DESIGN.md §4.1).

    GET  /health                  liveness
    POST /session                 create a session
    WS   /session/{id}/stream     bidirectional streaming turn
    GET  /tools                   list available tools (native + MCP)
    POST /mcp/connect             register an MCP server at runtime (M2)

The CLI and, later, the Tauri app both talk to exactly these endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from ..agent.loop import AgentLoop
from ..config import Config, get_config
from ..events import ErrorEvent, to_wire
from ..providers.anthropic import AnthropicProvider
from ..providers.base import ProviderError
from ..session.store import SessionStore
from ..tools.registry import ToolRegistry

DEFAULT_SYSTEM = "You are a helpful AI assistant running inside the agent-me kernel."


@dataclass
class KernelState:
    config: Config
    store: SessionStore
    tools: ToolRegistry

    def build_loop(self) -> AgentLoop:
        """Construct the agent loop on demand.

        The provider is built lazily so cheap endpoints (/health, /session,
        /tools) work without an API key; a missing key only fails an actual
        conversation turn, where the error is surfaced to the client.
        """
        provider = AnthropicProvider(
            api_key=self.config.anthropic_api_key or "", model=self.config.model
        )
        return AgentLoop(provider, self.store, self.tools, system=DEFAULT_SYSTEM)


def build_state(config: Config | None = None) -> KernelState:
    config = config or get_config()
    store = SessionStore(config.session_dir)
    tools = ToolRegistry()  # empty in M0; native tools register here in M1.
    return KernelState(config=config, store=store, tools=tools)


def create_app(config: Config | None = None) -> FastAPI:
    app = FastAPI(title="agent-me kernel", version="0.0.1")

    # Provider construction can fail (missing key); defer it so /health works
    # even before a key is configured, and surface the error on first use.
    state: dict[str, KernelState] = {}

    def get_state() -> KernelState:
        if "kernel" not in state:
            state["kernel"] = build_state(config)
        return state["kernel"]

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    @app.post("/session")
    async def create_session() -> dict[str, str]:
        session = get_state().store.create()
        return {"id": session.id}

    @app.get("/tools")
    async def list_tools() -> dict[str, list]:
        tools = get_state().tools
        return {
            "tools": [
                {"name": t.name, "description": t.description, "source": t.source}
                for t in tools.list()
            ]
        }

    @app.post("/mcp/connect")
    async def mcp_connect() -> JSONResponse:
        # M2. Registering an external MCP server at runtime.
        return JSONResponse(
            status_code=501,
            content={"detail": "MCP connect is not implemented until M2."},
        )

    @app.websocket("/session/{session_id}/stream")
    async def stream(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        kernel = get_state()

        session = kernel.store.get(session_id)
        if session is None:
            await websocket.send_json(
                to_wire(ErrorEvent(message=f"Unknown session: {session_id}"))
            )
            await websocket.close()
            return

        try:
            loop = kernel.build_loop()
        except ProviderError as exc:
            await websocket.send_json(to_wire(ErrorEvent(message=str(exc))))
            await websocket.close()
            return

        try:
            while True:
                payload = await websocket.receive_json()
                user_input = payload.get("input", "")
                if not user_input:
                    continue
                try:
                    async for event in loop.run_turn(session, user_input):
                        await websocket.send_json(to_wire(event))
                except ProviderError as exc:
                    await websocket.send_json(to_wire(ErrorEvent(message=str(exc))))
        except WebSocketDisconnect:
            # Client went away; the kernel keeps the session alive (DESIGN.md §4.2).
            return

    return app
