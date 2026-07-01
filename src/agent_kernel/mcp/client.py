"""Hand-rolled MCP client — M2.

Scope for M2 (DESIGN.md §6, §9): talk to *one* real, well-behaved MCP server
end-to-end before generalizing. Planned pieces:

- transport: stdio and/or HTTP+SSE
- JSON-RPC framing and request/response correlation
- capability negotiation / handshake
- `list_tools` discovery + schema translation into `tools.ToolRegistry`
- timeouts and handling of malformed/slow responses

Intentionally unimplemented in M0. Do not build this out until M1's exit
criterion is met.
"""

from __future__ import annotations


class MCPClient:
    def __init__(self) -> None:
        raise NotImplementedError("MCP client lands in M2 — see DESIGN.md §7.")
