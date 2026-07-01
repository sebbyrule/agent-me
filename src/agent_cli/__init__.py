"""agent_cli — a thin REPL client over the kernel's WS API (DESIGN.md §4.2).

Holds no agent logic: it creates a session, opens the streaming WebSocket, and
renders tokens/tool events as they arrive.
"""

__version__ = "0.0.1"
