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


def create_run_bot_use_case(
    settings: Settings,
    strategy_path: str,
    live_data: bool = False,
) -> RunBotUseCase:
    """Create a fully wired run-bot use case.

    When ``live_data`` is True the Hyperliquid websocket stream is used
    instead of the in-memory stub (dry-run only — no orders placed).
    """
    mode = TradingMode(settings.mode)
    if live_data:
        from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
            HyperliquidMarketDataStream,
        )

        stream = HyperliquidMarketDataStream(
            stale_data_seconds=settings.stale_data_seconds,
        )
    else:
        stream = InMemoryMarketDataStream()
    return RunBotUseCase(
        exchange_gateway=_build_exchange_gateway(settings, mode),
        market_data_stream=stream,
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


def create_live_trading_runtime_use_case(
    strategy_path: str,
    symbol: str,
    interval: str,
    *,
    mode: str = "dry_run",
    live_data: bool = False,
    warmup_bars: list | None = None,
    bot_loop=None,
):
    """Create a fully wired LiveTradingRuntimeUseCase.

    Loads the YAML strategy, creates a real ``RuleBasedStrategyEvaluator``
    via the factory, and wires all adapters.  Never uses the placeholder
    ``FinbarStrategyEvaluator`` in the live path.

    When *bot_loop* is provided, the stream is owned by the bot loop
    and ``market_data_stream`` is set to ``None`` on the use case.
    """
    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )
    from finbot.core.domain.entities.trading_mode import TradingMode
    from finbot.core.domain.services.enrichment_validator import (
        EnrichmentValidator,
    )
    from finbot.core.domain.services.order_planner import OrderPlanner
    from finbot.core.domain.services.risk_gates.duplicate_signal_gate import (
        DuplicateSignalGate,
    )
    from finbot.core.domain.services.risk_gates.mode_gate import ModeGate
    from finbot.infrastructure.adapters.rule_based_strategy_evaluator_factory import (
        RuleBasedStrategyEvaluatorFactory,
    )
    from finbot.infrastructure.strategy.pandas_bar_frame_converter import (
        PandasBarFrameConverter,
    )
    from finbot.infrastructure.strategy.pandas_ta_indicator_calculator import (
        PandasTaIndicatorCalculator,
    )
    from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
        YamlStrategyDefinitionLoader,
    )

    trading_mode = TradingMode(mode)
    if trading_mode in (TradingMode.TESTNET, TradingMode.LIVE):
        repo = create_bot_state_repository()
    else:
        repo = create_in_memory_repository()

    # When a bot_loop is provided, it owns the stream — don't create a second one.
    if bot_loop is not None:
        stream = None  # type: ignore[assignment]
    elif live_data:
        from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
            HyperliquidMarketDataStream,
        )

        settings = Settings()
        stream = HyperliquidMarketDataStream(
            stale_data_seconds=settings.stale_data_seconds,
        )
    else:
        from finbot.infrastructure.adapters.in_memory_market_data_stream import (
            InMemoryMarketDataStream,
        )

        stream = InMemoryMarketDataStream()

    # Load YAML strategy and create real evaluator
    loader = YamlStrategyDefinitionLoader()
    definition = loader.load_from_file(strategy_path)
    strategy_hash = _hash_strategy_file(strategy_path)
    evaluator = RuleBasedStrategyEvaluatorFactory().create(
        definition=definition,
        symbol=symbol,
        interval=interval,
        strategy_hash=strategy_hash,
    )

    # Collect required indicator columns from strategy definition
    required_columns = {ind.name for ind in definition.indicators}

    return LiveTradingRuntimeUseCase(
        exchange_gateway=_build_exchange_gateway(Settings(), trading_mode),
        market_data_stream=stream,
        strategy_evaluator=evaluator,
        state_repository=repo,
        indicator_calculator=PandasTaIndicatorCalculator(),
        enrichment_validator=EnrichmentValidator(),
        bar_frame_converter=PandasBarFrameConverter(),
        mode=trading_mode,
        warmup_bars=warmup_bars,
        required_columns=required_columns,
        order_planner=OrderPlanner(
            gates=[
                ModeGate(),
                DuplicateSignalGate(repo),
            ]
        ),
        bot_loop=bot_loop,
    )


def _hash_strategy_file(path: str) -> str:
    """Return a hex digest of the strategy file contents."""
    import hashlib

    from finbot.core.domain.entities.strategy_load_error import StrategyLoadError

    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError as e:
        raise StrategyLoadError(f"Cannot read strategy file for hashing: {e}") from e
