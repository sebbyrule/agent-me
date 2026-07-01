"""agent_kernel — the long-running agent process.

Owns all state and logic: the agent loop, provider adapters, tool registry,
hand-rolled MCP, and session store. Frontends (CLI, desktop) are thin clients
over the API in `agent_kernel.api`. See DESIGN.md §3–4.
"""

__version__ = "0.0.1"
