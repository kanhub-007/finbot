"""Composition root for Finbot services."""

from finbot.config.settings import Settings
from finbot.core.application.dto.run_bot_request import RunBotRequest
from finbot.core.application.use_cases.run_bot import RunBotUseCase
from finbot.core.application.use_cases.validate_strategy_definition import (
    ValidateStrategyUseCase,
)
from finbot.core.domain.entities.bot_config import BotConfig
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.infrastructure.adapters.dry_run_exchange_gateway import (
    DryRunExchangeGateway,
)
from finbot.infrastructure.adapters.finbar_strategy_evaluator import (
    FinbarStrategyEvaluator,
)
from finbot.infrastructure.adapters.hyperliquid_exchange_gateway import (
    HyperliquidExchangeGateway,
)
from finbot.infrastructure.adapters.in_memory_market_data_stream import (
    InMemoryMarketDataStream,
)
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)


def create_bot_config(settings: Settings) -> BotConfig:
    """Create a domain bot configuration from environment settings."""
    return BotConfig(
        mode=TradingMode(settings.mode),
        live_trading_ack=settings.live_trading_ack,
        max_position_usd=settings.max_position_usd,
        max_daily_loss_usd=settings.max_daily_loss_usd,
        max_open_orders=settings.max_open_orders,
        stale_data_seconds=settings.stale_data_seconds,
    )


def _build_exchange_gateway(settings: Settings, mode: TradingMode) -> ExchangeGateway:
    """Create the correct exchange gateway for the given mode.

    Uses a registry-like dispatch so adding testnet/live sub-modes does not
    require nested ternaries.
    """
    if mode == TradingMode.DRY_RUN:
        return DryRunExchangeGateway()
    return HyperliquidExchangeGateway()


def create_run_bot_use_case(settings: Settings, strategy_path: str) -> RunBotUseCase:
    """Create a fully wired run-bot use case."""
    mode = TradingMode(settings.mode)
    return RunBotUseCase(
        exchange_gateway=_build_exchange_gateway(settings, mode),
        market_data_stream=InMemoryMarketDataStream(),
        strategy_evaluator=FinbarStrategyEvaluator(strategy_path),
        state_repository=InMemoryBotStateRepository(),
    )


def create_run_bot_request(
    settings: Settings,
    strategy_path: str,
    symbol: str,
    interval: str,
) -> RunBotRequest:
    """Create a run-bot request DTO from CLI and environment values."""
    return RunBotRequest(
        strategy_path=strategy_path,
        symbol=symbol,
        interval=interval,
        config=create_bot_config(settings),
    )


def create_validate_strategy_use_case() -> ValidateStrategyUseCase:
    """Create a fully wired validate-strategy use case."""
    return ValidateStrategyUseCase(loader=YamlStrategyDefinitionLoader())
