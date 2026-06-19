"""MCP tools — finbot operations exposed to MCP clients.

Each tool group lives in its own module and is registered via
a ``register_*_tools(mcp, bot_manager)`` function called by
:func:`register_tools`. Tools capture ``bot_manager`` in their closures
(S8 / H4) — they do not read it off the FastMCP instance.
"""

from typing import Any

from fastmcp import FastMCP

from .bot_control import register_bot_control_tools
from .bot_history import register_bot_history_tools
from .safety import register_safety_tools
from .util import register_util_tools


def register_tools(
    mcp: FastMCP,
    bot_manager: Any,
    *,
    settings: Any | None = None,
    validate_strategy_use_case: Any | None = None,
) -> None:
    """Register all finbot MCP tools on the given server instance."""
    register_bot_control_tools(mcp, bot_manager, settings=settings)
    register_bot_history_tools(mcp, bot_manager)
    register_safety_tools(mcp, bot_manager)
    register_util_tools(
        mcp, bot_manager, validate_strategy_use_case=validate_strategy_use_case
    )
