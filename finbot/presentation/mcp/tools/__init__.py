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
    validate_strategy_use_case: Any | None = None,
) -> None:
    """Register all finbot MCP tools on the given server instance.

    Parameters
    ----------
    mcp:
        FastMCP server tools are registered on.
    bot_manager:
        Passed into every tool group so each tool closes over it (H4).
    validate_strategy_use_case:
        Optional pre-built use case so ``validate_strategy`` doesn't
        rebuild it per call (M2). When ``None``, the util tool falls
        back to constructing one per call (legacy behaviour).
    """
    register_bot_control_tools(mcp, bot_manager)
    register_bot_history_tools(mcp, bot_manager)
    register_safety_tools(mcp, bot_manager)
    register_util_tools(
        mcp, bot_manager, validate_strategy_use_case=validate_strategy_use_case
    )
