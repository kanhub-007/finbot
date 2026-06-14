"""MCP tools — finbot operations exposed to MCP clients.

Each tool group lives in its own module and is registered via
a ``register_*_tools(mcp)`` function called by :func:`register_tools`.
"""

from fastmcp import FastMCP

from .bot_control import register_bot_control_tools
from .bot_history import register_bot_history_tools
from .safety import register_safety_tools
from .util import register_util_tools


def register_tools(mcp: FastMCP) -> None:
    """Register all finbot MCP tools on the given server instance."""
    register_bot_control_tools(mcp)
    register_bot_history_tools(mcp)
    register_safety_tools(mcp)
    register_util_tools(mcp)
