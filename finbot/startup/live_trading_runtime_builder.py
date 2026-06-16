"""LiveTradingRuntimeBuilder — fluent builder for LiveTradingRuntimeUseCase."""

from __future__ import annotations

from typing import Any

from finbot.core.application.use_cases.live_trading_runtime import (
    LiveTradingRuntimeUseCase,
)
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.interfaces.bar_frame_converter import (
    BarFrameConverter,
)
from finbot.core.domain.interfaces.bot_loop import BotLoop
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.cloid_generator import CloidGenerator
from finbot.core.domain.interfaces.enrichment_validator import (
    EnrichmentValidator,
)
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.interfaces.indicator_calculator import (
    IndicatorCalculator,
)
from finbot.core.domain.interfaces.market_metadata_provider import (
    MarketMetadataProvider,
)
from finbot.core.domain.interfaces.order_normalizer import OrderNormalizer
from finbot.core.domain.interfaces.order_planner import OrderPlanner
from finbot.core.domain.interfaces.order_submission_strategy import (
    OrderSubmissionStrategy,
)
from finbot.core.domain.interfaces.runtime_event_emitter import (
    RuntimeEventEmitter,
)
from finbot.core.domain.interfaces.strategy_evaluator import (
    StrategyEvaluator,
)
from finbot.core.domain.interfaces.strategy_validator import (
    StrategyValidator,
)


class LiveTradingRuntimeBuilder:
    """Fluent builder for constructing a LiveTradingRuntimeUseCase.

    Usage::

        runtime = (
            LiveTradingRuntimeBuilder()
            .with_exchange(gateway)
            .with_evaluator(evaluator)
            .with_repository(repo)
            .with_indicator_calculator(calc)
            .with_enrichment_validator(validator)
            .with_bar_converter(converter)
            .with_mode(TradingMode.DRY_RUN)
            .with_submission_strategy(submission)
            .with_event_emitter(emitter)
            .build()
        )

    Only 8 parameters are required; the rest are optional and default
    to None. The builder enforces that required fields are set at
    ``build()`` time.
    """

    def __init__(self) -> None:
        self._exchange: ExchangeGateway | None = None
        self._evaluator: StrategyEvaluator | None = None
        self._repo: BotStateRepository | None = None
        self._indicator_calc: IndicatorCalculator | None = None
        self._enrichment_validator: EnrichmentValidator | None = None
        self._bar_converter: BarFrameConverter | None = None
        self._mode: TradingMode | None = None
        self._submission_strategy: OrderSubmissionStrategy | None = None
        self._event_emitter: RuntimeEventEmitter | None = None

        # Optional
        self._warmup_bars: list[dict[str, Any]] | None = None
        self._required_columns: set[str] | None = None
        self._required_indicators: list[str] | None = None
        self._order_planner: OrderPlanner | None = None
        self._metadata_provider: MarketMetadataProvider | None = None
        self._order_normalizer: OrderNormalizer | None = None
        self._cloid_generator: CloidGenerator | None = None
        self._bot_loop: BotLoop | None = None
        self._strategy_validator: StrategyValidator | None = None
        self._live_state: Any | None = None

    # -- required setters ---------------------------------------------------

    def with_exchange(self, gateway: ExchangeGateway) -> LiveTradingRuntimeBuilder:
        self._exchange = gateway
        return self

    def with_evaluator(
        self, evaluator: StrategyEvaluator
    ) -> LiveTradingRuntimeBuilder:
        self._evaluator = evaluator
        return self

    def with_repository(
        self, repo: BotStateRepository
    ) -> LiveTradingRuntimeBuilder:
        self._repo = repo
        return self

    def with_indicator_calculator(
        self, calc: IndicatorCalculator
    ) -> LiveTradingRuntimeBuilder:
        self._indicator_calc = calc
        return self

    def with_enrichment_validator(
        self, validator: EnrichmentValidator
    ) -> LiveTradingRuntimeBuilder:
        self._enrichment_validator = validator
        return self

    def with_bar_converter(
        self, converter: BarFrameConverter
    ) -> LiveTradingRuntimeBuilder:
        self._bar_converter = converter
        return self

    def with_mode(self, mode: TradingMode) -> LiveTradingRuntimeBuilder:
        self._mode = mode
        return self

    def with_submission_strategy(
        self, strategy: OrderSubmissionStrategy
    ) -> LiveTradingRuntimeBuilder:
        self._submission_strategy = strategy
        return self

    def with_event_emitter(
        self, emitter: RuntimeEventEmitter
    ) -> LiveTradingRuntimeBuilder:
        self._event_emitter = emitter
        return self

    # -- optional setters ---------------------------------------------------

    def with_warmup_bars(
        self, bars: list[dict[str, Any]] | None
    ) -> LiveTradingRuntimeBuilder:
        self._warmup_bars = bars
        return self

    def with_required_columns(
        self, columns: set[str] | None
    ) -> LiveTradingRuntimeBuilder:
        self._required_columns = columns
        return self

    def with_required_indicators(
        self, indicators: list[str] | None
    ) -> LiveTradingRuntimeBuilder:
        self._required_indicators = indicators
        return self

    def with_order_planner(
        self, planner: OrderPlanner | None
    ) -> LiveTradingRuntimeBuilder:
        self._order_planner = planner
        return self

    def with_metadata_provider(
        self, provider: MarketMetadataProvider | None
    ) -> LiveTradingRuntimeBuilder:
        self._metadata_provider = provider
        return self

    def with_order_normalizer(
        self, normalizer: OrderNormalizer | None
    ) -> LiveTradingRuntimeBuilder:
        self._order_normalizer = normalizer
        return self

    def with_cloid_generator(
        self, gen: CloidGenerator | None
    ) -> LiveTradingRuntimeBuilder:
        self._cloid_generator = gen
        return self

    def with_bot_loop(
        self, loop: BotLoop | None
    ) -> LiveTradingRuntimeBuilder:
        self._bot_loop = loop
        return self

    def with_strategy_validator(
        self, validator: StrategyValidator | None
    ) -> LiveTradingRuntimeBuilder:
        self._strategy_validator = validator
        return self

    def with_live_state(
        self, state: Any | None
    ) -> LiveTradingRuntimeBuilder:
        self._live_state = state
        return self

    # -- build --------------------------------------------------------------

    def build(self) -> LiveTradingRuntimeUseCase:
        """Construct the runtime, validating required fields."""
        if self._exchange is None:
            raise ValueError("exchange_gateway is required")
        if self._evaluator is None:
            raise ValueError("strategy_evaluator is required")
        if self._repo is None:
            raise ValueError("state_repository is required")
        if self._indicator_calc is None:
            raise ValueError("indicator_calculator is required")
        if self._enrichment_validator is None:
            raise ValueError("enrichment_validator is required")
        if self._bar_converter is None:
            raise ValueError("bar_frame_converter is required")
        if self._mode is None:
            raise ValueError("mode is required")
        if self._submission_strategy is None:
            raise ValueError("submission_strategy is required")
        if self._event_emitter is None:
            raise ValueError("event_emitter is required")

        return LiveTradingRuntimeUseCase(
            exchange_gateway=self._exchange,
            strategy_evaluator=self._evaluator,
            state_repository=self._repo,
            indicator_calculator=self._indicator_calc,
            enrichment_validator=self._enrichment_validator,
            bar_frame_converter=self._bar_converter,
            mode=self._mode,
            submission_strategy=self._submission_strategy,
            event_emitter=self._event_emitter,
            warmup_bars=self._warmup_bars,
            required_columns=self._required_columns,
            required_indicators=self._required_indicators,
            order_planner=self._order_planner,
            market_metadata_provider=self._metadata_provider,
            order_normalizer=self._order_normalizer,
            cloid_generator=self._cloid_generator,
            bot_loop=self._bot_loop,
            strategy_validator=self._strategy_validator,
            live_state=self._live_state,
        )
