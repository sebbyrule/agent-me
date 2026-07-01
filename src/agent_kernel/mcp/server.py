"""Hand-rolled MCP server — M5.

Exposes the kernel's own tools to *other* MCP clients (e.g. Claude Desktop).
Comes only after the client side (M2) works. Stub for now.
"""

from __future__ import annotations


class MCPServer:
    def __init__(self) -> None:
        raise NotImplementedError("MCP server lands in M5 — see DESIGN.md §7.")
