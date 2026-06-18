"""MCP tools — bot control (start/stop/status)."""

import json

from fastmcp import FastMCP

from finbot.config.settings import Settings
from finbot.core.domain.services.mode_url_guard import (
    check_mode_url_consistency,
)

from ._shared import _get_bot_manager


def register_bot_control_tools(mcp: FastMCP) -> None:
    """Register start_bot, stop_bot, and get_bot_status MCP tools."""

    @mcp.tool(
        name="start_bot",
        description=(
            "Start a Finbot trading runtime with a YAML strategy. "
            "Supports dry_run (paper trading), testnet (testnet execution), "
            "and live modes. Only one bot can run at a time. "
            "Use live_trading_ack=true when starting testnet/live mode. "
            "Returns the bot_run_id on success."
        ),
    )
    def start_bot(
        strategy_path: str,
        symbol: str = "BTC",
        interval: str = "1h",
        mode: str = "dry_run",
        warmup_bars: int = 100,
        live_trading_ack: bool = False,
    ) -> str:
        """Start a bot with the given strategy and parameters."""
        # C4: refuse mode/URL combinations that would route orders to the
        # wrong environment before touching the BotManager.  Mirrors the
        # CLI guard in cli/main.py:_cmd_run.
        reasons = check_mode_url_consistency(
            mode=mode,
            hyperliquid_testnet=Settings().hyperliquid_testnet,
        )
        if reasons:
            return json.dumps(
                {"status": "rejected", "message": "; ".join(reasons)},
                indent=2,
            )

        manager = _get_bot_manager(mcp)
        result = manager.start(
            strategy_path=strategy_path,
            symbol=symbol,
            interval=interval,
            mode=mode,
            warmup_bars=warmup_bars,
            live_trading_ack=live_trading_ack,
        )
        return json.dumps(result, indent=2)

    @mcp.tool(
        name="stop_bot",
        description=(
            "Stop the currently running bot. Safe to call when no bot "
            "is running — returns 'no_bot_running' status."
        ),
    )
    def stop_bot() -> str:
        """Stop the running bot."""
        manager = _get_bot_manager(mcp)
        return json.dumps(manager.stop(), indent=2)

    @mcp.tool(
        name="get_bot_status",
        description=(
            "Get the current bot status. If a bot is running, returns live "
            "state including last candle timestamp, last signal, position, "
            "and cumulative counts. If no bot is running, returns summary "
            "of the most recently completed run."
        ),
    )
    def get_bot_status() -> str:
        """Return the current bot status snapshot."""
        manager = _get_bot_manager(mcp)
        return json.dumps(manager.get_status(), indent=2, default=str)
