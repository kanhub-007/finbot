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
from finbot.infrastructure.services.strategy_file_hasher import hash_strategy_file
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)
from finbot.startup.service_factory import (
    build_exchange_gateway,
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
    from finbot.core.domain.services.risk_gates.registry import (
        build_default_gates,
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

    gateway = build_exchange_gateway(settings, trading_mode)

    if bot_loop is None and live_data:
        # Build informative streams for MTF / cross-asset.
        # One MarketDataStream per unique (symbol, interval) pair.
        # Duplicate pairs share a single websocket — both aliases receive
        # the same candles via the callback.
        info_streams, info_aliases_list, info_symbols_list = _build_informative_streams(
            settings, timeframes, symbol
        )
        bot_loop = create_bot_loop(
            settings,
            gateway,
            account=trading_mode in (TradingMode.TESTNET, TradingMode.LIVE),
            informative_streams=info_streams if info_streams else None,
            informative_aliases=info_aliases_list if info_aliases_list else None,
            informative_symbols=info_symbols_list if info_symbols_list else None,
        )

    loader = YamlStrategyDefinitionLoader()
    definition = loader.load_from_file(strategy_path)
    strategy_hash = hash_strategy_file(strategy_path)

    # Resolve MTF timeframes from the strategy YAML (ADR-10).
    # When the strategy declares a ``timeframes`` block, the YAML primary
    # overrides the caller's interval and informative intervals are
    # auto-discovered.
    timeframes = loader.last_timeframes()
    informative_intervals: list[str] = []
    if timeframes is not None and timeframes.is_mtf:
        interval = timeframes.primary or interval
        informative_intervals = list(timeframes.informative_intervals)
        logger.info(
            "MTF strategy detected: primary=%s, informative=%s",
            interval,
            informative_intervals,
        )

    # Per-informative warmup bars, keyed by alias (resolved from the loader's
    # alias→interval map). Seeded from historical bars and passed to the runtime
    # so the shared MultiTimeframeBarEnricher has informative history.
    informative_warmup_bars: dict[str, list] = {}
    if timeframes is not None and timeframes.is_mtf:
        for alias, info_interval in timeframes.informative_aliases.items():
            # Reserve the alias key even before bars load so the runtime knows
            # which informatives to expect.
            informative_warmup_bars.setdefault(alias, [])

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
    # Load informative warmup bars (MTF / cross-asset), keyed by alias.
    # Cross-asset informatives load from their declared symbol; same-symbol
    # informatives (symbol=None) fall back to the primary symbol.
    if live_data and informative_warmup_bars:
        aliases = timeframes.informative_aliases if timeframes else {}
        for alias, info_interval in aliases.items():
            info_symbol = (
                timeframes.effective_symbol(alias, symbol)
                if timeframes
                else symbol
            )
            info_bars = _load_warmup_bars(info_symbol, info_interval, min_bars=100)
            logger.info(
                "Loaded %d warmup bars for informative %s/%s (alias=%s)",
                len(info_bars),
                info_symbol,
                info_interval,
                alias,
            )
            informative_warmup_bars[alias] = info_bars

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
        gates=build_default_gates(
            mode=trading_mode.value,
            live_trading_ack=settings.live_trading_ack,
            stale_data_seconds=settings.stale_data_seconds,
            max_position_usd=settings.max_position_usd,
            max_leverage=settings.max_leverage,
            max_open_orders=settings.max_open_orders,
            max_daily_loss_usd=settings.max_daily_loss_usd,
            repo=repo,
        )
    )

    builder = (
        LiveTradingRuntimeBuilder()
        .with_exchange(gateway)
        .with_evaluator(evaluator)
        .with_repository(repo)
        .with_indicator_calculator(SharedRuntimeIndicatorCalculator())
        .with_bar_enricher(_build_bar_enricher(loader))
        .with_required_data_validator(_make_required_data_validator())
        .with_causal_streaming_enricher(_build_causal_streaming_enricher(loader))
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
        .with_strategy_log_writer(_make_log_writer())
        .with_interval(interval)
        .with_informative_intervals(
            informative_intervals if informative_intervals else None
        )
        .with_informative_warmup_bars(
            informative_warmup_bars if informative_warmup_bars else None
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
        logger.info(
            "Warmup bar load failed for %s/%s: %s — "
            "will warm up from live candles instead "
            "(normal for new or low-volume tokens)",
            symbol,
            interval,
            e,
        )
        return []


def _build_informative_streams(
    settings: Settings,
    timeframes: object | None,
    primary_symbol: str,
) -> tuple[list, list[str], list[str | None]]:
    """Build MarketDataStream instances for each unique (symbol, interval) pair.

    Returns three parallel lists:
        streams:  one ``HyperliquidMarketDataStream`` per unique pair
        aliases:  alias for each stream (used as informative label)
        symbols:  symbol for each stream (``None`` = use primary)

    Duplicate (symbol, interval) pairs share a single websocket.
    """
    from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
        HyperliquidMarketDataStream,
    )
    from finbot.startup.service_factory import hyperliquid_base_url

    if timeframes is None or not getattr(timeframes, "is_mtf", False):
        return [], [], []

    base = hyperliquid_base_url(settings)
    deduped: dict[tuple[str, str], list[str]] = {}
    for alias, interval in timeframes.informative_aliases.items():
        eff = timeframes.effective_symbol(alias, primary_symbol)
        key = (eff, interval)
        deduped.setdefault(key, []).append(alias)

    streams: list = []
    all_aliases: list[str] = []
    all_symbols: list[str | None] = []

    for (eff_symbol, interval), aliases_for_pair in deduped.items():
        stream = HyperliquidMarketDataStream(
            base_url=base,
            stale_data_seconds=settings.stale_data_seconds,
        )
        streams.append(stream)
        all_aliases.append(aliases_for_pair[0])
        is_cross = eff_symbol.upper() != primary_symbol.upper()
        all_symbols.append(eff_symbol if is_cross else None)
        if len(aliases_for_pair) > 1:
            logger.info(
                "Sharing websocket for %s/%s across aliases %s",
                eff_symbol,
                interval,
                aliases_for_pair,
            )

    return streams, all_aliases, all_symbols


def _make_log_writer():
    """Create a shared StrategyLogWriter for the runtime."""
    from finbot.infrastructure.services.strategy_log_writer import (
        StrategyLogWriter,
    )

    return StrategyLogWriter()


def _build_causal_streaming_enricher(loader: YamlStrategyDefinitionLoader):
    """Build the causal MTF streaming enricher from the parsed strategy.

    Returns ``None`` for strategies with no parsed definition (the runtime
    then falls back to the batch enricher or legacy path).
    """
    definition = loader.last_definition()
    if definition is None:
        return None
    from finbar_strategy_runtime.indicators.causal_multi_timeframe_streaming_enricher import (  # noqa: E501
        CausalMultiTimeframeStreamingEnricher,
    )

    return CausalMultiTimeframeStreamingEnricher.from_strategy_definition(
        definition=definition,
        primary_indicators=list(loader.last_primary_required_indicators()),
        informative_indicators=loader.last_informative_required_indicators(),
    )


def _build_bar_enricher(loader: YamlStrategyDefinitionLoader):
    """Build the shared MultiTimeframeBarEnricher adapter for the strategy.

    Returns ``None`` for strategies with no parsed definition (the runtime
    then falls back to the legacy single-TF indicator path).
    """
    definition = loader.last_definition()
    if definition is None:
        return None
    from finbot.infrastructure.strategy.shared_runtime_multi_timeframe_enricher import (
        SharedRuntimeMultiTimeframeEnricher,
    )

    return SharedRuntimeMultiTimeframeEnricher(
        definition=definition,
        primary_required_indicators=loader.last_primary_required_indicators(),
        informative_required_indicators=loader.last_informative_required_indicators(),
    )


def _make_required_data_validator():
    """Build the shared RequiredDataValidator adapter (data-driven warmup)."""
    from finbot.infrastructure.strategy.shared_runtime_required_data_validator import (
        SharedRuntimeRequiredDataValidator,
    )

    return SharedRuntimeRequiredDataValidator()
