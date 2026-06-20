"""Composition root for the LiveTradingRuntimeUseCase (S10).

Extracted from ``service_factory.py`` to keep that file under the 500-line
size limit. Builds the full runtime: YAML strategy → evaluator →
risk-gate chain → submission strategy → builder.

Accepts ``settings`` as an explicit parameter (M8) rather than reading
``Settings()`` inline, so callers (BotManager factory, CLI) can inject
a pre-built instance.
"""

from __future__ import annotations

import logging
from typing import Any

from finbot.config.settings import Settings
from finbot.core.domain.services.content_hash import hash_strategy_file
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)
from finbot.startup.service_factory import (
    _build_exchange_gateway,
    create_bot_loop,
    create_bot_state_repository,
    create_in_memory_repository,
    create_validate_strategy_use_case,
)

logger = logging.getLogger(__name__)


def create_live_trading_runtime_use_case(
    strategy_path: str,
    symbol: str,
    interval: str,
    *,
    mode: str = "dry_run",
    live_data: bool = False,
    warmup_bars: list | None = None,
    bot_loop: Any | None = None,
    notification_sender: object | None = None,
    settings: Settings | None = None,
) -> Any:
    """Create a fully wired LiveTradingRuntimeUseCase.

    Loads the YAML strategy, creates a real ``SharedRuntimeStrategyEvaluator``
    via the shared runtime factory, and wires all adapters.  Never uses a
    placeholder evaluator in the live path.

    Parameters
    ----------
    settings:
        Pre-built Settings instance (M8). When ``None``, reads from the
        environment via ``Settings()`` — retained for backwards compatibility
        with callers that don't supply one.
    """
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
    settings = settings or Settings()
    if trading_mode in (TradingMode.TESTNET, TradingMode.LIVE):
        repo = create_bot_state_repository()
    elif settings.database_path and settings.database_path not in (
        "data/finbot.db",
        "",
    ):
        repo = create_bot_state_repository()
    else:
        repo = create_in_memory_repository()

    gateway = _build_exchange_gateway(settings, trading_mode)

    if bot_loop is None and live_data:
        bot_loop = create_bot_loop(
            settings,
            gateway,
            account=trading_mode in (TradingMode.TESTNET, TradingMode.LIVE),
        )

    loader = YamlStrategyDefinitionLoader()
    definition = loader.load_from_file(strategy_path)
    strategy_hash = hash_strategy_file(strategy_path)

    from finbot.core.application.use_cases.account_event_handler import (
        AccountEventHandler,
    )
    from finbot.core.domain.services.trade_ledger import TradeLedger
    from finbot.infrastructure.adapters import (
        shared_runtime_strategy_evaluator_factory as _eval_factory_mod,
    )

    trade_ledger = TradeLedger(repo, strategy_hash=strategy_hash)
    evaluator = _eval_factory_mod.SharedRuntimeStrategyEvaluatorFactory().create(
        definition=definition,
        symbol=symbol,
        interval=interval,
        strategy_hash=strategy_hash,
    )

    required_columns = set(loader.last_required_columns())
    required_indicators = loader.last_required_indicators()
    # When the strategy declares no indicators, fall back to computing
    # all required columns as indicators.  This is resolved here so the
    # runtime does not need a hidden ``or`` fallback.
    if not required_indicators:
        required_indicators = list(required_columns)

    if warmup_bars is None and live_data:
        warmup_bars = _load_warmup_bars(symbol, interval, min_bars=100)

    from finbot.infrastructure.adapters.simple_runtime_event_emitter import (
        SimpleRuntimeEventEmitter,
    )
    from finbot.startup.live_trading_runtime_builder import (
        LiveTradingRuntimeBuilder,
    )

    metadata_provider, normalizer, submission_strategy = _build_submission(
        trading_mode, gateway, repo, trade_ledger, symbol
    )

    event_emitter = SimpleRuntimeEventEmitter()
    if notification_sender is not None:
        from finbot.core.domain.events.runtime_events import (
            RiskTriggeredEvent,
        )
        from finbot.infrastructure.adapters.telegram_runtime_observer import (
            TelegramRuntimeObserver,
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
            MaxLeverageGate(max_leverage=settings.max_leverage),
            MaxOpenOrdersGate(max_orders=settings.max_open_orders),
            DailyLossGate(max_loss_usd=settings.max_daily_loss_usd),
            ReduceOnlyGate(),
            DuplicateSignalGate(repo),
        ]
    )

    builder = (
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
        .with_strategy_loader(loader)
        .with_trade_ledger(trade_ledger)
        .with_account_event_handler(
            AccountEventHandler(repo, trade_ledger, notification_sender)
        )
    )
    if trading_mode != TradingMode.DRY_RUN:
        from finbot.core.domain.services.cloid_generator import CloidGenerator

        builder = builder.with_metadata_provider(metadata_provider)
        builder = builder.with_cloid_generator(CloidGenerator())
        if normalizer is not None:
            builder = builder.with_order_normalizer(normalizer)
    return builder.build()


def _build_submission(trading_mode, gateway, repo, trade_ledger, symbol):
    """Build the mode-specific submission strategy + normalizer + metadata."""
    from finbot.core.domain.entities.trading_mode import TradingMode

    if trading_mode == TradingMode.DRY_RUN:
        from finbot.infrastructure.adapters.dry_run_submission_strategy import (
            DryRunSubmissionStrategy,
        )

        return (
            None,
            None,
            DryRunSubmissionStrategy(repo, trade_ledger, exchange=gateway),
        )
    from finbot.core.domain.services.order_normalizer import OrderNormalizer
    from finbot.infrastructure.adapters.hyperliquid_metadata_provider import (
        HyperliquidMetadataProvider,
    )
    from finbot.infrastructure.adapters.live_order_executor import LiveOrderExecutor
    from finbot.infrastructure.adapters.live_submission_strategy import (
        LiveSubmissionStrategy,
    )

    metadata_provider = HyperliquidMetadataProvider()
    metadata = metadata_provider.get_metadata(symbol)
    normalizer = OrderNormalizer(metadata=metadata) if metadata is not None else None
    executor = LiveOrderExecutor(gateway, normalizer, repo)
    return (
        metadata_provider,
        normalizer,
        LiveSubmissionStrategy(
            gateway,
            order_normalizer=normalizer,
            repo=repo,
            executor=executor,
        ),
    )


def _load_warmup_bars(
    symbol: str,
    interval: str,
    min_bars: int = 100,
) -> list[dict]:
    """Load historical bars from Hyperliquid for warmup.

    Returns an empty list if the API call fails (runtime will warm
    up from live candles instead).
    """
    from finbot.infrastructure.strategy.hyperliquid_bar_source import (
        HyperliquidBarSource,
    )

    try:
        source = HyperliquidBarSource()
        bars = source.load_bars(symbol, interval, min_bars)
        logger.info("Loaded %d warmup bars for %s/%s", len(bars), symbol, interval)
        return bars
    except Exception as e:  # noqa: BLE001 - degrade gracefully to live warmup
        logger.warning("Warmup bar load failed for %s: %s", symbol, e)
        return []
