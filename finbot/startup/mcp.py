"""MCP server startup — composition root for the MCP transport.

Creates the FastMCP server, wires dependencies, and provides the CLI runner.
Follows the same pattern as finbar and kapsula.
"""

import logging
import os
import time
from collections.abc import Callable

from dotenv import load_dotenv
from fastmcp import FastMCP

from finbot.config.settings import Settings
from finbot.core.domain.services.bot_manager import BotManager
from finbot.startup.mcp_server import FinbotMcpServer
from finbot.startup.service_factory import (
    create_bot_config,
    create_bot_state_repository,
    create_live_trading_runtime_use_case,
    create_telegram_exchange_gateway,
)

load_dotenv()
logger = logging.getLogger(__name__)


def _make_runtime_factory(
    settings: Settings,
    telegram_ref: Callable[[], object | None] | None = None,
):
    """Return a callable that creates a LiveTradingRuntimeUseCase.

    The callable accepts the same kwargs that BotManager.start() passes
    and delegates to ``create_live_trading_runtime_use_case`` in the
    composition root.

    ``telegram_ref`` is a *callable* (not a captured value) so the
    dispatcher is resolved **lazily**, at factory-call time. Telegram
    starts *after* the BotManager is constructed; a snapshot of
    ``notification_sender`` at construction time would always be ``None``
    and silently drop every runtime-emitted risk event (C3).
    """

    def factory(
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        live_data: bool = True,
        warmup_bars: int = 100,
    ):
        notification_sender = None
        if telegram_ref is not None:
            telegram = telegram_ref()
            if telegram is not None:
                notification_sender = telegram.notification_dispatcher
        return create_live_trading_runtime_use_case(
            strategy_path=strategy_path,
            symbol=symbol,
            interval=interval,
            mode=mode,
            live_data=live_data,
            notification_sender=notification_sender,
        )

    return factory


def create_server() -> FinbotMcpServer:
    """Build the MCP server with all dependencies wired.

    Returns:
        Wrapped FastMCP server instance ready to run.
    """
    settings = Settings()
    repo = create_bot_state_repository(migrate=True)
    exchange = create_telegram_exchange_gateway(settings)

    # Telegram integration (optional, background thread).
    # ``telegram_holder`` lets the runtime factory resolve the dispatcher
    # lazily — Telegram starts after the BotManager below is built.
    telegram_holder: list[object | None] = [None]
    telegram = None
    if settings.telegram_enabled:
        from finbot.infrastructure.repositories.sqlite_telegram_chat_repository import (
            SqliteTelegramChatRepository,
        )
        from finbot.startup.telegram import create_telegram_control_plane

        chat_repo = SqliteTelegramChatRepository(settings.database_path)
        telegram = create_telegram_control_plane(settings, chat_repo=chat_repo)
        telegram_holder[0] = telegram

    from finbot.infrastructure.adapters.dotenv_config_writer import (
        DotEnvConfigWriter,
    )
    from finbot.infrastructure.adapters.hyperliquid_metadata_provider import (
        HyperliquidMetadataProvider,
    )

    bot_manager = BotManager(
        runtime_factory=_make_runtime_factory(
            settings, telegram_ref=lambda: telegram_holder[0]
        ),
        repository=repo,
        exchange=exchange,
        settings=settings,
        create_bot_config=lambda s: create_bot_config(s),
        startup_time=time.time(),
        metadata_provider=HyperliquidMetadataProvider(),
        config_writer=DotEnvConfigWriter(),
    )

    server = FastMCP(
        name="finbot",
        instructions=(
            "Finbot is a live trading runtime for Finbar YAML strategies. "
            "It connects to Hyperliquid and executes trading strategies "
            "on live market data."
            "\n\n"
            "RUNTIME:\n"
            "• start_bot / stop_bot / get_bot_status\n"
            "• list_bot_runs / get_bot_run_results\n"
            "• validate_strategy / ping / panic / get_audit_log\n"
            "\n"
            "TRADING (requires activate_symbol first):\n"
            "• get_balance / get_price / get_position / get_leverage\n"
            "• set_leverage / activate_symbol / get_active_symbol\n"
            "• place_long_order / place_short_order\n"
            "• close_position / set_stop_loss / set_take_profit\n"
            "• list_open_orders / cancel_order / clear_all\n"
            "\n"
            "LOGS:\n"
            "• list_strategy_logs / get_strategy_log\n"
            "\n"
            "SAFETY NOTES:\n"
            "• Default mode is dry_run — no real orders placed.\n"
            "• Testnet/live require live_trading_ack=true.\n"
            "• Only one bot can run at a time."
        ),
    )

    # bot_manager is captured in the FinbotMcpServer wrapper (below).

    # Wire Telegram if enabled
    if telegram is not None:
        telegram.attach_bot_manager(bot_manager)
        telegram.start_in_background()
        # telegram is captured in the FinbotMcpServer wrapper (below).
        logger.info(
            "Telegram bot started (allowed users: %d)",
            len(settings.telegram_allowed_user_ids),
        )

    # Register all MCP tools. Build the validate_strategy use case once
    # here (M2) — the util tool reuses this instance on every call instead
    # of rebuilding it (which would re-import finbar_strategy_runtime and
    # rebuild capability sets per invocation).
    from finbot.presentation.mcp.tools import register_tools
    from finbot.startup.service_factory import create_validate_strategy_use_case

    register_tools(
        server,
        bot_manager,
        settings=settings,
        validate_strategy_use_case=create_validate_strategy_use_case(),
        log_reader=_make_log_reader(),
    )

    config = get_transport_config()
    logger.info("MCP server configured: transport=%s", config["transport"])
    if config["transport"] == "http":
        logger.info("HTTP transport: %s:%s", config["host"], config["port"])

    return FinbotMcpServer(server=server, bot_manager=bot_manager, telegram=telegram)


def get_transport_config() -> dict:
    """Read transport configuration from environment variables."""
    return {
        "transport": os.getenv("FINBOT_TRANSPORT", "stdio").lower(),
        "host": os.getenv("FINBOT_HOST", "127.0.0.1"),
        "port": int(os.getenv("FINBOT_PORT", "8006")),
    }


def run() -> None:
    """Start the MCP server. Called by CLI entry points."""
    server = create_server()
    config = get_transport_config()

    if config["transport"] == "http":
        logger.info(
            "Starting MCP server on http://%s:%s",
            config["host"],
            config["port"],
        )
        server.run(
            transport="streamable-http",
            host=config["host"],
            port=config["port"],
        )
    else:
        logger.info("Starting MCP server on stdio")
        server.run(transport="stdio")


def _make_log_reader():
    """Create the strategy log reader for MCP log tools."""
    from finbot.infrastructure.services.strategy_log_writer import (
        StrategyLogFileReader,
    )

    return StrategyLogFileReader()
