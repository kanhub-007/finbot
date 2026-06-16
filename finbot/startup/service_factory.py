"""Composition root for Finbot services."""

import hashlib

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
from finbot.infrastructure.adapters.hyperliquid_exchange_gateway import (
    HyperliquidExchangeGateway,
)
from finbot.infrastructure.adapters.in_memory_market_data_stream import (
    InMemoryMarketDataStream,
)
from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
    SharedRuntimeStrategyEvaluatorFactory,
)
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)
from finbot.infrastructure.strategy.csv_bar_loader import CsvBarLoader
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

# Hyperliquid REST endpoints — single source of truth for URL selection.
_MAINNET_URL = "https://api.hyperliquid.xyz"
_TESTNET_URL = "https://api.hyperliquid-testnet.xyz"


def hyperliquid_base_url(settings: Settings) -> str:
    """Return the Hyperliquid REST URL for the configured environment."""
    return _TESTNET_URL if settings.hyperliquid_testnet else _MAINNET_URL


def create_bot_config(settings: Settings) -> BotConfig:
    """Create a domain bot configuration from environment settings."""
    return BotConfig(
        mode=TradingMode(settings.mode),
        live_trading_ack=settings.live_trading_ack,
        max_position_usd=settings.max_position_usd,
        max_daily_loss_usd=settings.max_daily_loss_usd,
        max_open_orders=settings.max_open_orders,
        stale_data_seconds=settings.stale_data_seconds,
        private_key=settings.hyperliquid_private_key.get_secret_value(),
        db_path=settings.database_path,
    )


def _build_exchange_gateway(settings: Settings, mode: TradingMode) -> ExchangeGateway:
    """Create the correct exchange gateway for the given mode.

    Dry-run uses a no-op gateway; testnet/live use the real Hyperliquid
    gateway wired with credentials and the environment-appropriate URL.
    """
    if mode == TradingMode.DRY_RUN:
        return DryRunExchangeGateway()
    return HyperliquidExchangeGateway(
        private_key=settings.hyperliquid_private_key.get_secret_value(),
        base_url=hyperliquid_base_url(settings),
        account_address=settings.hyperliquid_account_address,
        vault_address=settings.hyperliquid_vault_address,
    )


def create_exchange_gateway(settings: Settings) -> ExchangeGateway:
    """Create a Hyperliquid exchange gateway from settings.

    Used by kill-switch / panic commands that need the gateway directly.
    """
    return _build_exchange_gateway(settings, TradingMode(settings.mode))


def create_run_bot_use_case(
    settings: Settings,
    strategy_path: str,
    symbol: str = "",
    interval: str = "",
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
            base_url=hyperliquid_base_url(settings),
            stale_data_seconds=settings.stale_data_seconds,
        )
    else:
        stream = InMemoryMarketDataStream()
    return RunBotUseCase(
        exchange_gateway=_build_exchange_gateway(settings, mode),
        market_data_stream=stream,
        strategy_evaluator=_build_strategy_evaluator(strategy_path, symbol, interval),
        state_repository=InMemoryBotStateRepository(),
    )


def _build_strategy_evaluator(strategy_path: str, symbol: str, interval: str):
    """Load a strategy file and wrap its package strategy in a Finbot adapter.

    Used by legacy validate-and-exit wiring; the live runtime builds its
    own evaluator via the shared factory.
    """
    from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator

    loader = YamlStrategyDefinitionLoader()
    definition = loader.load_from_file(strategy_path)
    strategy_hash = _hash_strategy_file(strategy_path)
    evaluator: StrategyEvaluator = SharedRuntimeStrategyEvaluatorFactory().create(
        definition=definition,
        symbol=symbol,
        interval=interval,
        strategy_hash=strategy_hash,
    )
    return evaluator


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
    import finbar_strategy_runtime as _runtime

    from finbot.infrastructure.adapters.package_capability_provider import (
        supported_indicator_types,
        supported_stop_loss_types,
    )

    return ValidateStrategyUseCase(
        loader=YamlStrategyDefinitionLoader(),
        supported_indicators=supported_indicator_types(),
        supported_risk_types=supported_stop_loss_types(),
        runtime_package_version=_runtime.__version__,
    )


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
        evaluator_factory=SharedRuntimeStrategyEvaluatorFactory(),
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


def create_bot_loop(
    settings: Settings,
    gateway: ExchangeGateway | None = None,
    *,
    account: bool = False,
):
    """Create the market-data (and optional account) event loop.

    Parameters
    ----------
    settings:
        Runtime settings (stale-data threshold, testnet flag, credentials).
    gateway:
        Exchange gateway whose SDK ``Exchange`` backs the account stream.
        Required when ``account=True``.
    account:
        When ``True`` (testnet/live), subscribe to user fills and order
        updates so lifecycle/fill handling is fed by real exchange events.
    """
    from finbot.infrastructure.adapters.bot_event_loop import BotEventLoop
    from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
        HyperliquidMarketDataStream,
    )
    from finbot.infrastructure.adapters.thread_safe_event_queue import (
        ThreadSafeEventQueue,
    )

    queue = ThreadSafeEventQueue()
    stream = HyperliquidMarketDataStream(
        base_url=hyperliquid_base_url(settings),
        stale_data_seconds=settings.stale_data_seconds,
    )
    account_stream = None
    if account:
        if gateway is None:
            raise ValueError("account=True requires an exchange gateway")
        from finbot.infrastructure.adapters.hyperliquid_account_data_stream import (
            HyperliquidAccountDataStream,
        )
        from finbot.infrastructure.adapters.hyperliquid_exchange_gateway import (
            HyperliquidExchangeGateway,
        )

        if not isinstance(gateway, HyperliquidExchangeGateway):
            raise ValueError("account stream requires a HyperliquidExchangeGateway")
        account_stream = HyperliquidAccountDataStream(
            exchange=gateway.get_exchange(),
            queue=queue,
            user_address=settings.hyperliquid_account_address,
            account_cache=gateway.account_cache(),
        )
    return BotEventLoop(queue, stream, account_stream=account_stream)


def create_live_trading_runtime_use_case(
    strategy_path: str,
    symbol: str,
    interval: str,
    *,
    mode: str = "dry_run",
    live_data: bool = False,
    warmup_bars: list | None = None,
    bot_loop=None,
    notification_sender: object | None = None,
):
    """Create a fully wired LiveTradingRuntimeUseCase.

    Loads the YAML strategy, creates a real ``SharedRuntimeStrategyEvaluator``
    via the shared runtime factory, and wires all adapters.  Never uses a
    placeholder evaluator in the live path.

    When ``live_data`` is True (or *bot_loop* is omitted on the
    testnet/live path) a :class:`BotEventLoop` owning the market data
    stream — plus an account stream for testnet/live — is built here so
    all wiring lives in the composition root.
    """
    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )
    from finbot.core.domain.entities.trading_mode import TradingMode
    from finbot.core.domain.services.enrichment_validator import (
        EnrichmentValidator,
    )
    from finbot.core.domain.services.order_planner import OrderPlanner
    from finbot.core.domain.services.risk_gates.daily_loss_gate import (
        DailyLossGate,
    )
    from finbot.core.domain.services.risk_gates.duplicate_signal_gate import (
        DuplicateSignalGate,
    )
    from finbot.core.domain.services.risk_gates.max_leverage_gate import (
        MaxLeverageGate,
    )
    from finbot.core.domain.services.risk_gates.max_open_orders_gate import (
        MaxOpenOrdersGate,
    )
    from finbot.core.domain.services.risk_gates.max_position_gate import (
        MaxPositionGate,
    )
    from finbot.core.domain.services.risk_gates.mode_gate import ModeGate
    from finbot.core.domain.services.risk_gates.reduce_only_gate import (
        ReduceOnlyGate,
    )
    from finbot.core.domain.services.risk_gates.stale_data_gate import (
        StaleDataGate,
    )
    from finbot.infrastructure.strategy.pandas_bar_frame_converter import (
        PandasBarFrameConverter,
    )
    from finbot.infrastructure.strategy.shared_runtime_indicator_calculator import (
        SharedRuntimeIndicatorCalculator,
    )

    trading_mode = TradingMode(mode)
    settings = Settings()
    if trading_mode in (TradingMode.TESTNET, TradingMode.LIVE):
        repo = create_bot_state_repository()
    elif settings.database_path and settings.database_path not in (
        "data/finbot.db",
        "",
    ):
        # Dry-run with explicit database path — use SQLite for persistent audit
        repo = create_bot_state_repository()
    else:
        repo = create_in_memory_repository()

    gateway = _build_exchange_gateway(settings, trading_mode)

    # Build the bot loop + account stream in the composition root unless the
    # caller supplied one (tests inject fakes).
    if bot_loop is None and live_data:
        bot_loop = create_bot_loop(
            settings,
            gateway,
            account=trading_mode in (TradingMode.TESTNET, TradingMode.LIVE),
        )

    # Load YAML strategy and create real evaluator
    loader = YamlStrategyDefinitionLoader()
    definition = loader.load_from_file(strategy_path)
    strategy_hash = _hash_strategy_file(strategy_path)

    from finbot.core.domain.services.trade_ledger import TradeLedger

    trade_ledger = TradeLedger(repo, strategy_hash=strategy_hash)
    evaluator = SharedRuntimeStrategyEvaluatorFactory().create(
        definition=definition,
        symbol=symbol,
        interval=interval,
        strategy_hash=strategy_hash,
    )

    # Required enriched columns come from the package validation result
    # (concrete, directly-referenced columns), not the strategy-local aliases.
    required_columns = set(loader.last_required_columns())
    # The indicator calculator must compute the FULL declared chain, including
    # intermediate indicators (vp_vah/vp_val) that only feed composites
    # (above_value). required_columns alone omits them and the composites read
    # NaN. The list order matters too: the package calculator computes
    # indicators in order, so composites must follow their intermediates.
    required_indicators = loader.last_required_indicators()

    # Pre-load warmup bars from Hyperliquid when using live data
    if warmup_bars is None and live_data:
        warmup_bars = _load_warmup_bars(symbol, interval, min_bars=100)

    # Wire the mode-specific submission strategy
    from finbot.infrastructure.adapters.dry_run_submission_strategy import (
        DryRunSubmissionStrategy,
    )
    from finbot.infrastructure.adapters.live_submission_strategy import (
        LiveSubmissionStrategy,
    )
    from finbot.infrastructure.adapters.simple_runtime_event_emitter import (
        SimpleRuntimeEventEmitter,
    )
    from finbot.startup.live_trading_runtime_builder import (
        LiveTradingRuntimeBuilder,
    )

    if trading_mode == TradingMode.DRY_RUN:
        submission_strategy = DryRunSubmissionStrategy(repo, trade_ledger)
    else:
        submission_strategy = LiveSubmissionStrategy(
            gateway, order_normalizer=None, repo=repo
        )

    # Wire the event emitter + Telegram observer (if available)
    event_emitter = SimpleRuntimeEventEmitter()
    if notification_sender is not None:
        from finbot.infrastructure.adapters.telegram_runtime_observer import (
            TelegramRuntimeObserver,
        )
        from finbot.core.domain.events.runtime_events import (
            RiskTriggeredEvent,
        )

        observer = TelegramRuntimeObserver(notification_sender)
        event_emitter.subscribe(RiskTriggeredEvent, observer.on_risk_triggered)

    order_planner = OrderPlanner(
        gates=[
            ModeGate(
                mode=trading_mode.value,
                live_trading_ack=settings.live_trading_ack,
            ),
            StaleDataGate(max_age_seconds=settings.stale_data_seconds),
            MaxPositionGate(max_notional_usd=settings.max_position_usd),
            MaxLeverageGate(),
            MaxOpenOrdersGate(max_orders=settings.max_open_orders),
            DailyLossGate(max_loss_usd=settings.max_daily_loss_usd),
            ReduceOnlyGate(),
            DuplicateSignalGate(repo),
        ]
    )

    return (
        LiveTradingRuntimeBuilder()
        .with_exchange(gateway)
        .with_evaluator(evaluator)
        .with_repository(repo)
        .with_indicator_calculator(SharedRuntimeIndicatorCalculator())
        .with_enrichment_validator(EnrichmentValidator())
        .with_bar_converter(PandasBarFrameConverter())
        .with_mode(trading_mode)
        .with_submission_strategy(submission_strategy)
        .with_event_emitter(event_emitter)
        .with_warmup_bars(warmup_bars)
        .with_required_columns(required_columns)
        .with_required_indicators(required_indicators)
        .with_order_planner(order_planner)
        .with_bot_loop(bot_loop)
        .with_strategy_validator(create_validate_strategy_use_case())
        .build()
    )


def _hash_strategy_file(path: str) -> str:
    """Return a hex digest of the strategy file contents."""
    from finbot.core.domain.entities.strategy_load_error import StrategyLoadError

    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError as e:
        raise StrategyLoadError(f"Cannot read strategy file for hashing: {e}") from e


def _load_warmup_bars(
    symbol: str,
    interval: str,
    min_bars: int = 100,
) -> list[dict]:
    """Load historical bars from Hyperliquid for warmup.

    Handles both standard perps and HIP-3 ``dex:COIN`` symbols.
    Returns an empty list if the API call fails (runtime will warm
    up from live candles instead).
    """
    import logging

    from finbot.infrastructure.strategy.hyperliquid_bar_source import (
        HyperliquidBarSource,
    )

    logger = logging.getLogger(__name__)
    try:
        source = HyperliquidBarSource()
        bars = source.load_bars(symbol, interval, min_bars)
        logger.info("Loaded %d warmup bars for %s/%s", len(bars), symbol, interval)
        return bars
    except Exception as e:  # noqa: BLE001 - degrade gracefully to live warmup
        logger.warning("Warmup bar load failed for %s: %s", symbol, e)
        return []
