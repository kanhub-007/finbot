"""MCP tools — safety (panic / emergency stop)."""

import json

from fastmcp import FastMCP

from ._shared import _get_bot_manager


def register_safety_tools(mcp: FastMCP) -> None:
    """Register the panic MCP tool."""

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
        manager = _get_bot_manager(mcp)
        result: dict[str, object] = {}

        # Stop the bot first
        stop_result = manager.stop()
        result["bot_stopped"] = stop_result["status"] == "stopped"

        if not manager.has_exchange:
            result["message"] = (
                "No exchange gateway wired — orders not cancelled."
            )
            return json.dumps(result, indent=2)

        if cancel_orders and symbol:
            cancel_result = manager.cancel_all_orders(symbol)
            result["cancel_orders"] = cancel_result

        if close_position and symbol:
            close_result = manager.close_position(symbol)
            result["close_position"] = close_result

        return json.dumps(result, indent=2, default=str)
