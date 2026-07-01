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
from ..events import ErrorEvent, PermissionRequest, ToolCallStart, to_wire
from ..permissions import PermissionPolicy, RiskLevel
from ..providers import ProviderError, create_provider
from ..session.store import SessionStore
from ..tools import register_native_tools
from ..tools.registry import ToolRegistry

DEFAULT_SYSTEM = "You are a helpful AI assistant running inside the agent-me kernel."


@dataclass
class KernelState:
    config: Config
    store: SessionStore
    tools: ToolRegistry
    policy: PermissionPolicy

    def build_loop(self) -> AgentLoop:
        """Construct the agent loop on demand.

        The provider is built lazily so cheap endpoints (/health, /session,
        /tools) work without an API key; a missing/misconfigured provider only
        fails an actual conversation turn, where the error is surfaced to the
        client. Which provider is used comes from config (DESIGN.md §5).
        """
        provider = create_provider(self.config)
        return AgentLoop(
            provider,
            self.store,
            self.tools,
            policy=self.policy,
            system=DEFAULT_SYSTEM,
        )


def build_state(config: Config | None = None) -> KernelState:
    config = config or get_config()
    store = SessionStore(config.session_dir)
    tools = ToolRegistry()
    register_native_tools(tools)  # M1: file read/write/list + shell exec.
    policy = PermissionPolicy(mode=config.tool_policy)
    return KernelState(config=config, store=store, tools=tools, policy=policy)


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
                {
                    "name": t.name,
                    "description": t.description,
                    "risk": t.risk.value,
                    "source": t.source,
                }
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

        async def confirm(call: ToolCallStart, risk: RiskLevel) -> bool:
            # Ask the client to approve a risky tool call, then wait for its
            # permission_response (DESIGN.md §8). The kernel owns policy; the
            # frontend owns the confirmation UX.
            await websocket.send_json(
                to_wire(
                    PermissionRequest(
                        id=call.id,
                        name=call.name,
                        risk=risk.value,
                        arguments=call.arguments,
                    )
                )
            )
            response = await websocket.receive_json()
            return bool(response.get("approved"))

        try:
            while True:
                payload = await websocket.receive_json()
                user_input = payload.get("input", "")
                if not user_input:
                    continue
                try:
                    async for event in loop.run_turn(session, user_input, confirm):
                        await websocket.send_json(to_wire(event))
                except ProviderError as exc:
                    await websocket.send_json(to_wire(ErrorEvent(message=str(exc))))
        except WebSocketDisconnect:
            # Client went away; the kernel keeps the session alive (DESIGN.md §4.2).
            return

    return app
