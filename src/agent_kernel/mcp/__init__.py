"""Hand-rolled MCP (DESIGN.md §6). Written from scratch on purpose — the official
SDK is reference only. The client (M2) connects out to one real server and folds
its tools into the registry via the manager; the server (M5) will expose the
kernel's own tools.
"""

from .client import MCPClient, MCPError
from .manager import MCPManager

__all__ = ["MCPClient", "MCPError", "MCPManager"]
