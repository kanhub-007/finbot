"""MCP tools — bot control (start/stop/status)."""

import json
from typing import Any

from fastmcp import FastMCP

from finbot.config.settings import Settings
from finbot.core.domain.services.mode_url_guard import (
    check_mode_url_consistency,
)


def register_bot_control_tools(
    mcp: FastMCP, bot_manager: Any, settings: Any = None
) -> None:
    """Register start_bot, stop_bot, and get_bot_status MCP tools.

    ``bot_manager`` is captured in each tool closure (S8 / H4) — tools no
    longer read a private attribute off the FastMCP instance. ``settings``
    is captured once (S13 / H9) so the tool does not re-instantiate
    ``Settings()`` per call.
    """

    @mcp.tool(
        name="start_bot",
        description=(
            "Start a Finbot trading runtime with a YAML strategy. "
            "Supports dry_run (paper trading), testnet (testnet execution), "
            "and live modes. Only one bot can run at a time. "
            "Use live_trading_ack=true when starting testnet/live mode. "
            "The interval is auto-detected from the strategy YAML when "
            "not specified (use an empty string ''). For MTF strategies "
            "with a timeframes block, the primary interval overrides "
            "any passed value. Informative intervals are auto-discovered. "
            "Returns the bot_run_id and resolved intervals on success."
        ),
    )
    def start_bot(
        strategy_path: str,
        symbol: str = "BTC",
        interval: str = "",
        mode: str = "dry_run",
        warmup_bars: int = 100,
        live_trading_ack: bool = False,
    ) -> str:
        """Start a bot — interval auto-detected from strategy YAML when empty."""
        _settings = settings or Settings()
        reasons = check_mode_url_consistency(
            mode=mode,
            hyperliquid_testnet=_settings.hyperliquid_testnet,
        )
        if reasons:
            return json.dumps(
                {"status": "rejected", "message": "; ".join(reasons)},
                indent=2,
            )

        result = bot_manager.start(
            strategy_path=strategy_path,
            symbol=symbol,
            interval=interval or "",
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
        return json.dumps(bot_manager.stop(), indent=2)

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
        return json.dumps(bot_manager.get_status(), indent=2, default=str)
