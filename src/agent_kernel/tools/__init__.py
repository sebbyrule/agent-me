"""Tool registry. Empty of real tools in M0 — native tools arrive in M1,
MCP-discovered tools in M2, both through the same `ToolRegistry`.
"""

from .native import register_native_tools
from .registry import Tool, ToolRegistry

__all__ = ["Tool", "ToolRegistry", "register_native_tools"]
