"""Integration test: the live runtime enriches with the REAL package calculator.

This is the test that should always have existed. It wires the actual
``SharedRuntimeIndicatorCalculator`` + ``SharedRuntimeStrategyEvaluator``
through ``LiveTradingRuntimeUseCase`` and proves the full indicator
chain computes (intermediate indicators like vp_vah/vp_val feed composites
like above_value/acceptance_into_value). The fake indicator engine used
elsewhere ignores its ``indicators`` argument, so it could never catch a
mismatch between "what the calculator is asked to compute" and "what the
validator requires".
"""

from decimal import Decimal

from finbot.core.application.use_cases.live_trading_runtime import (
    LiveTradingRuntimeUseCase,
)
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator
from finbot.core.domain.services.enrichment_validator import EnrichmentValidator
from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
    SharedRuntimeStrategyEvaluatorFactory,
)
from finbot.infrastructure.strategy.pandas_bar_frame_converter import (
    PandasBarFrameConverter,
)
from finbot.infrastructure.strategy.shared_runtime_indicator_calculator import (
    SharedRuntimeIndicatorCalculator,
)
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)
from tests.fakes import (
    InMemoryExchangeGateway,
    StubBotStateRepository,
    closed_warmup_bars,
    make_dry_run_submission_strategy,
    make_event_emitter,
    new_closed_candle,
)

AMT_DIP = "tests/fixtures/strategies/amt_dip_buyer_final.yaml"


class _RecordingEvaluator(StrategyEvaluator):
    """Wrap the real evaluator and capture the bar it received.

    Classical-school: asserts on the observable state (the enriched bar),
    not on interactions. If enrichment is invalid the runtime never calls
    the evaluator, so an empty record proves the pipeline stalled.
    """

    def __init__(self, inner: StrategyEvaluator) -> None:
        self._inner = inner
        self.received_bar: dict | None = None

    def evaluate(self, enriched_bar: dict, position) -> SignalDecision:
        self.received_bar = dict(enriched_bar)
        return self._inner.evaluate(enriched_bar, position)


def _flat_position() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="BTC", direction=PositionDirection.FLAT, size=Decimal("0")
    )


def test_real_calculator_composes_intermediate_indicators() -> None:
    """The runtime must ask the calculator to compute ALL declared indicators
    (required_indicators), not just the columns directly referenced by
    conditions (required_columns).

    For the AMT strategy, above_value/acceptance_into_value are composites
    that depend on the intermediate vp_vah/vp_val. If only required_columns
    is passed to the calculator, vp_vah/vp_val are never computed and the
    composites read NaN — the validator then rejects every bar and the
    strategy HODLs forever in a real live session.
    """
    loader = YamlStrategyDefinitionLoader()
    definition = loader.load_from_file(AMT_DIP)
    real_evaluator = SharedRuntimeStrategyEvaluatorFactory().create(
        definition, symbol="BTC", interval="1h", strategy_hash="real-calc"
    )
    recording = _RecordingEvaluator(real_evaluator)

    runtime = LiveTradingRuntimeUseCase(
        exchange_gateway=InMemoryExchangeGateway(),
        strategy_evaluator=recording,
        state_repository=StubBotStateRepository(),
        indicator_calculator=SharedRuntimeIndicatorCalculator(),
        enrichment_validator=EnrichmentValidator(),
        bar_frame_converter=PandasBarFrameConverter(),
        mode=TradingMode.DRY_RUN,
        submission_strategy=make_dry_run_submission_strategy(
            StubBotStateRepository()
        ),
        event_emitter=make_event_emitter(),
        warmup_bars=closed_warmup_bars(120),
        required_columns=set(loader.last_required_columns()),
        required_indicators=loader.last_required_indicators(),
    )
    runtime._start_session(AMT_DIP, "real-calc", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    # The composites must be computed (non-NaN), so enrichment passes and the
    # evaluator is reached with a fully-enriched bar.
    assert result.enrichment_valid is True
    assert recording.received_bar is not None
    # The bug symptom is NaN (None in the dict), not a falsy boolean. Both
    # above_value and acceptance_into_value are boolean indicators that must
    # be computed — True or False — never missing.
    assert recording.received_bar["above_value"] is not None
    assert _is_computed(recording.received_bar["above_value"])
    assert _is_computed(recording.received_bar["acceptance_into_value"])


def _is_computed(value: object) -> bool:
    """True when an indicator value was computed (rejects None/NaN/inf).

    Boolean indicators (above_value/acceptance_into_value) are valid whether
    True or False; the bug symptom is NaN/None, not a falsy boolean.
    """
    import math

    if value is None:
        return False
    if isinstance(value, bool):
        return True  # a boolean indicator is fully computed
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)
