"""The hand-written native tools (DESIGN.md §7, M1) — sandboxed to a workspace.

read/list (safe), write (mutating), and shell (arbitrary exec). Each declares a
`RiskLevel` so the permission layer can gate it. All paths are confined to a
workspace root and `run_shell` executes there, so even an approved tool call
can't reach outside the workspace by path traversal (defense in depth alongside
the permission prompt).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..permissions import RiskLevel
from .registry import Tool, ToolRegistry


class WorkspaceError(ValueError):
    """Raised when a tool argument points outside the workspace root."""


def register_native_tools(registry: ToolRegistry, workspace: Path | str | None = None) -> None:
    root = Path(workspace).resolve() if workspace else Path.cwd().resolve()

    def resolve(rel: str) -> Path:
        target = (root / rel).resolve()
        if target == root or target.is_relative_to(root):
            return target
        raise WorkspaceError(f"Path is outside the workspace: {rel}")

    async def read_file(args: dict[str, Any]) -> str:
        return resolve(args["path"]).read_text(encoding="utf-8")

    async def list_dir(args: dict[str, Any]) -> list[str]:
        base = resolve(args.get("path", "."))
        if not base.is_dir():
            raise NotADirectoryError(f"Not a directory: {args.get('path', '.')}")
        return sorted(p.name + ("/" if p.is_dir() else "") for p in base.iterdir())

    async def write_file(args: dict[str, Any]) -> str:
        path = resolve(args["path"])
        content = args["content"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {path.relative_to(root).as_posix()}."

    async def run_shell(args: dict[str, Any]) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_shell(
            args["command"],
            cwd=str(root),  # confine execution to the workspace
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return {
            "exit_code": proc.returncode,
            "stdout": out.decode(errors="replace"),
            "stderr": err.decode(errors="replace"),
        }

    tools = [
        Tool(
            name="read_file",
            description="Read a UTF-8 text file (within the workspace) and return its contents.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=read_file,
            risk=RiskLevel.READ,
        ),
        Tool(
            name="list_dir",
            description="List a workspace directory (trailing '/' marks subdirectories).",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
            },
            handler=list_dir,
            risk=RiskLevel.READ,
        ),
        Tool(
            name="write_file",
            description="Write text to a file in the workspace, creating parent dirs. Overwrites.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=write_file,
            risk=RiskLevel.WRITE,
        ),
        Tool(
            name="run_shell",
            description="Run a shell command in the workspace; returns exit code, stdout, stderr.",
            input_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            handler=run_shell,
            risk=RiskLevel.EXEC,
        ),
    ]
    for tool in tools:
        registry.register(tool)
