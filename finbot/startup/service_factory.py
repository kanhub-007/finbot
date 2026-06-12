"""Composition root for Finbot services."""

from finbot.config.settings import Settings
from finbot.core.application.dto.run_bot_request import RunBotRequest
from finbot.core.application.use_cases.replay_strategy import (
    ReplayStrategyUseCase,
)
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
from finbot.infrastructure.adapters.rule_based_strategy_evaluator_factory import (
    RuleBasedStrategyEvaluatorFactory,
)
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)
from finbot.infrastructure.strategy.csv_bar_loader import CsvBarLoader
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


def create_replay_strategy_use_case(
    warmup_min_bars: int = 0,
) -> ReplayStrategyUseCase:
    """Create a fully wired replay-strategy use case.

    When ``warmup_min_bars`` is > 0 a :class:`WarmupWindow` is wired in
    so signals are suppressed until the minimum bar count is reached.
    """
    from finbot.core.domain.services.warmup_window import WarmupWindow

    warmup = None
    if warmup_min_bars:
        warmup = WarmupWindow(min_bars=warmup_min_bars)

    return ReplayStrategyUseCase(
        loader=YamlStrategyDefinitionLoader(),
        bar_loader=CsvBarLoader(),
        evaluator_factory=RuleBasedStrategyEvaluatorFactory(),
        warmup=warmup,
    )


def db_path_from_settings() -> str:
    return Settings().database_path or "data/finbot.db"


def create_bot_state_repository(*, migrate: bool = True):
    """Create the default SQLite bot state repository.

    Parameters
    ----------
    migrate:
        When ``True`` (default), pending schema migrations are applied
        before the repository is returned.  Set to ``False`` for
        read-only commands like ``status`` that should never trigger
        DDL.
    """
    from finbot.infrastructure.repositories.sqlite_bot_state_repository import (
        SqliteBotStateRepository,
    )

    db_path = db_path_from_settings()
    if migrate:
        from finbot.infrastructure.repositories.sqlite_migrator import (
            SqliteMigrator,
        )

        SqliteMigrator(db_path).migrate()
    return SqliteBotStateRepository(db_path)


def create_in_memory_repository():
    """Create an in-memory repository for tests/dry-runs."""
    from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
        InMemoryBotStateRepository,
    )

    return InMemoryBotStateRepository()


def create_status_use_case():
    """Create a fully wired status use case (read-only — no migrations)."""
    from finbot.core.application.use_cases.status import StatusUseCase

    return StatusUseCase(repo=create_bot_state_repository(migrate=False))
