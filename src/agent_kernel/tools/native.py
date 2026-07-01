"""The first hand-written native tools (DESIGN.md §7, M1).

Deliberately small — read/list (safe), write (mutating), and shell (arbitrary
exec). Each declares a `RiskLevel` so the permission layer can gate it; the
tools themselves stay dumb and do not make permission decisions.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..permissions import RiskLevel
from .registry import Tool, ToolRegistry


async def _read_file(args: dict[str, Any]) -> str:
    return Path(args["path"]).read_text(encoding="utf-8")


async def _list_dir(args: dict[str, Any]) -> list[str]:
    base = Path(args.get("path", "."))
    return sorted(
        p.name + ("/" if p.is_dir() else "") for p in base.iterdir()
    )


async def _write_file(args: dict[str, Any]) -> str:
    path = Path(args["path"])
    content = args["content"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {path}."


async def _run_shell(args: dict[str, Any]) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_shell(
        args["command"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return {
        "exit_code": proc.returncode,
        "stdout": out.decode(errors="replace"),
        "stderr": err.decode(errors="replace"),
    }


_NATIVE_TOOLS = [
    Tool(
        name="read_file",
        description="Read a UTF-8 text file and return its full contents.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=_read_file,
        risk=RiskLevel.READ,
    ),
    Tool(
        name="list_dir",
        description="List the entries of a directory (trailing '/' marks subdirectories).",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        },
        handler=_list_dir,
        risk=RiskLevel.READ,
    ),
    Tool(
        name="write_file",
        description="Write text to a file, creating parent directories as needed. Overwrites.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        handler=_write_file,
        risk=RiskLevel.WRITE,
    ),
    Tool(
        name="run_shell",
        description="Run a shell command and return its exit code, stdout, and stderr.",
        input_schema={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        handler=_run_shell,
        risk=RiskLevel.EXEC,
    ),
]


def register_native_tools(registry: ToolRegistry) -> None:
    for tool in _NATIVE_TOOLS:
        registry.register(tool)
