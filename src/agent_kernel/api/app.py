"""FastAPI app exposing the kernel's HTTP/WS surface (DESIGN.md §4.1).

    GET  /health                  liveness
    POST /session                 create a session
    WS   /session/{id}/stream     bidirectional streaming turn
    GET  /tools                   list available tools (native + MCP)
    POST /mcp/connect             register an MCP server at runtime (M2)

The CLI and, later, the Tauri app both talk to exactly these endpoints.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agent.loop import AgentLoop
from ..config import Config, get_config
from ..events import ErrorEvent, PermissionRequest, ToolCallStart, to_wire
from ..mcp import MCPManager
from ..permissions import PermissionPolicy, RiskLevel
from ..providers import ProviderError, create_provider
from ..session.store import SessionStore
from ..tools import register_native_tools
from ..tools.registry import ToolRegistry

DEFAULT_SYSTEM = "You are a helpful AI assistant running inside the agent-me kernel."


class MCPConnectRequest(BaseModel):
    """Body for POST /mcp/connect — spawn and register a stdio MCP server."""

    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] | None = None
    cwd: str | None = None


def _safe_path(root: Path, rel: str) -> Path | None:
    """Resolve `rel` under `root`, refusing anything that escapes it (M5 file
    viewer is read-only and sandboxed to the workspace root)."""
    target = (root / rel).resolve()
    root = root.resolve()
    if target == root or target.is_relative_to(root):
        return target
    return None


def _frontend_dir() -> Path | None:
    """Locate the desktop chat UI so the kernel can serve it (M4). The kernel
    stays usable headless if the directory is absent."""
    env = os.getenv("FRONTEND_DIR")
    if env:
        path = Path(env)
    elif getattr(sys, "frozen", False):
        # PyInstaller bundle: the UI is packaged next to the executable.
        path = Path(getattr(sys, "_MEIPASS", ".")) / "frontend"
    else:
        path = Path(__file__).resolve().parents[3] / "desktop" / "frontend"
    return path if path.is_dir() else None


@dataclass
class KernelState:
    config: Config
    store: SessionStore
    tools: ToolRegistry
    policy: PermissionPolicy
    mcp: MCPManager

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
    # Native file/shell tools are sandboxed to the workspace root.
    register_native_tools(tools, config.workspace_dir)
    policy = PermissionPolicy(mode=config.tool_policy)
    mcp = MCPManager(tools)  # M2: discovered tools register into the same registry.
    return KernelState(
        config=config, store=store, tools=tools, policy=policy, mcp=mcp
    )


def create_app(config: Config | None = None) -> FastAPI:
    # Provider construction can fail (missing key); defer it so /health works
    # even before a key is configured, and surface the error on first use.
    state: dict[str, KernelState] = {}

    def get_state() -> KernelState:
        if "kernel" not in state:
            state["kernel"] = build_state(config)
        return state["kernel"]

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        # Tear down any MCP server subprocesses on shutdown.
        if "kernel" in state:
            await state["kernel"].mcp.close_all()

    app = FastAPI(title="agent-me kernel", version="0.0.1", lifespan=lifespan)

    # The kernel binds to localhost only; allow any origin so both the
    # kernel-served UI and Tauri's bundled webview (a tauri:// origin) can reach
    # the API. No credentials are used, so "*" is safe here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": app.version,
            "provider": get_state().config.provider,
        }

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

    @app.get("/sessions")
    async def list_sessions() -> dict[str, list]:
        # Persisted sessions survive kernel restarts (DESIGN.md §4.1); a client
        # can reconnect to any of these ids.
        return {"sessions": get_state().store.list_sessions()}

    @app.get("/session/{session_id}")
    async def get_session(session_id: str):
        session = get_state().store.get(session_id)
        if session is None:
            return JSONResponse(status_code=404, content={"detail": "Unknown session"})
        return {"id": session.id, "messages": session.messages}

    @app.get("/files/tree")
    async def files_tree(path: str = "") -> JSONResponse:
        root = get_state().config.workspace_dir
        target = _safe_path(root, path)
        if target is None or not target.is_dir():
            return JSONResponse(status_code=404, content={"detail": "Not a directory"})
        entries = []
        for p in sorted(
            target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())
        ):
            entries.append(
                {
                    "name": p.name,
                    "path": p.relative_to(root).as_posix(),
                    "type": "dir" if p.is_dir() else "file",
                }
            )
        return JSONResponse(content={"path": path, "entries": entries})

    @app.get("/files/read")
    async def files_read(path: str) -> JSONResponse:
        root = get_state().config.workspace_dir
        target = _safe_path(root, path)
        if target is None or not target.is_file():
            return JSONResponse(status_code=404, content={"detail": "Not a file"})
        limit = 200_000
        data = target.read_bytes()
        return JSONResponse(
            content={
                "path": path,
                "content": data[:limit].decode("utf-8", errors="replace"),
                "truncated": len(data) > limit,
            }
        )

    @app.post("/mcp/connect")
    async def mcp_connect(request: MCPConnectRequest) -> JSONResponse:
        # Spawn a stdio MCP server, discover its tools, and register them
        # (DESIGN.md §4.1). Discovered tools then appear in /tools and are
        # invokable by the agent loop exactly like native tools.
        kernel = get_state()
        try:
            summary = await kernel.mcp.connect_stdio(
                name=request.name,
                command=request.command,
                args=request.args,
                env=request.env,
                cwd=request.cwd,
            )
        except ValueError as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc)})
        except Exception as exc:  # spawn/handshake/discovery failure
            return JSONResponse(
                status_code=502,
                content={"detail": f"Failed to connect MCP server: {exc}"},
            )
        return JSONResponse(content=summary)

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

    # Serve the desktop chat UI (M4) from the same origin as the API, so the
    # browser and Tauri's webview both talk to one kernel. Mounted last so it
    # never shadows an API route.
    frontend = _frontend_dir()
    if frontend is not None:

        @app.get("/")
        async def _root() -> RedirectResponse:
            return RedirectResponse(url="/app/")

        app.mount("/app", StaticFiles(directory=str(frontend), html=True), name="app")

    return app
