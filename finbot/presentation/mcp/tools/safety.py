"""MCP tools — safety (panic / emergency stop)."""

import json
from typing import Any

from fastmcp import FastMCP


def register_safety_tools(mcp: FastMCP, bot_manager: Any) -> None:
    """Register the panic MCP tool.

    ``bot_manager`` is captured in the tool closure (S8 / H4).
    """

    @mcp.tool(
        name="panic",
        description=(
            "Emergency stop — stops the running bot, cancels all open "
            "orders, and optionally market-closes the position. "
            "This bypasses risk gates intentionally (it is a kill switch). "
            "Safe to call in dry-run mode (bot stops, cancel is a no-op)."
        ),
    )
    def panic(
        cancel_orders: bool = True,
        close_position: bool = False,
        symbol: str = "",
    ) -> str:
        """Emergency stop with optional order cancellation and position close."""
        result: dict[str, object] = {}

        # Stop the bot first
        stop_result = bot_manager.stop()
        result["bot_stopped"] = stop_result["status"] == "stopped"

        if not bot_manager.has_exchange:
            result["message"] = "No exchange gateway wired — orders not cancelled."
            return json.dumps(result, indent=2)

        if cancel_orders and symbol:
            cancel_result = bot_manager.cancel_all_orders(symbol)
            result["cancel_orders"] = cancel_result

        if close_position and symbol:
            close_result = bot_manager.close_position(symbol)
            result["close_position"] = close_result

        return json.dumps(result, indent=2, default=str)
