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
from finbot.startup.service_factory import (
    create_bot_config,
    create_bot_state_repository,
    create_exchange_gateway,
    create_live_trading_runtime_use_case,
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


def create_server() -> FastMCP:
    """Build the FastMCP server with all dependencies wired.

    Returns:
        Configured FastMCP server instance ready to run.
    """
    settings = Settings()
    repo = create_bot_state_repository(migrate=True)
    exchange = create_exchange_gateway(settings)

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
            "QUICK REFERENCE:\n"
            "• start_bot(): Start a trading bot with a strategy file, "
            "symbol, interval, and mode (dry_run/testnet/live).\n"
            "• get_bot_status(): Check current bot state — running status, "
            "last candle, last signal, position, counts.\n"
            "• stop_bot(): Stop the running bot safely.\n"
            "• validate_strategy(): Check a strategy YAML file before running.\n"
            "• list_bot_runs(): See completed bot runs with summaries.\n"
            "• get_bot_run_results(): Get detailed signals/orders/fills "
            "for a specific run.\n"
            "• panic(): Emergency stop + cancel orders + optionally close "
            "position.\n"
            "• ping(): Health check — server status and exchange connectivity.\n"
            "• get_audit_log(): Retrieve recent audit log entries.\n"
            "\n"
            "SAFETY NOTES:\n"
            "• Default mode is dry_run — no real orders placed.\n"
            "• Testnet/live require live_trading_ack=true.\n"
            "• Only one bot can run at a time."
        ),
    )

    # Tools capture bot_manager via closure (S8 / H4). The manager is also
    # exposed as a public attribute so composition-root tests can drive the
    # runtime factory without re-deriving it.
    server.bot_manager = bot_manager  # type: ignore[attr-defined]

    # Wire Telegram if enabled
    if telegram is not None:
        telegram.attach_bot_manager(bot_manager)
        telegram.start_in_background()
        server._finbot_telegram = telegram  # type: ignore[attr-defined]
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
        validate_strategy_use_case=create_validate_strategy_use_case(),
    )

    config = get_transport_config()
    logger.info("MCP server configured: transport=%s", config["transport"])
    if config["transport"] == "http":
        logger.info("HTTP transport: %s:%s", config["host"], config["port"])

    return server


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
