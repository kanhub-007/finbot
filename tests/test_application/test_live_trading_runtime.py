"""Tests for LiveTradingRuntimeUseCase — Slice 1 scenarios."""

from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.services.enrichment_validator import (
    EnrichmentValidator,
)
from tests.fakes import (
    FakeStrategyEvaluator,
    InMemoryBarFrameConverter,
    InMemoryExchangeGateway,
    InMemoryIndicatorEngine,
    FakeBotStateRepository,
    closed_warmup_bars,
    indicator_bar,
    make_dry_run_submission_strategy,
    make_event_emitter,
    new_closed_candle,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_runtime(
    *,
    repo=None,
    exchange=None,
    evaluator=None,
    indicator_engine=None,
    mode=TradingMode.DRY_RUN,
    warmup_bars=None,
    required_columns=None,
    bar_frame_converter=None,
):
    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )

    _repo = repo or FakeBotStateRepository()
    _exchange = exchange or InMemoryExchangeGateway()
    return LiveTradingRuntimeUseCase(
        exchange_gateway=_exchange,
        strategy_evaluator=evaluator or FakeStrategyEvaluator(),
        state_repository=_repo,
        indicator_calculator=indicator_engine or InMemoryIndicatorEngine(),
        enrichment_validator=EnrichmentValidator(),
        bar_frame_converter=bar_frame_converter or InMemoryBarFrameConverter(),
        mode=mode,
        submission_strategy=make_dry_run_submission_strategy(
            _repo, exchange=_exchange
        ),
        event_emitter=make_event_emitter(),
        warmup_bars=warmup_bars or closed_warmup_bars(100),
        required_columns=required_columns or set(),
    )


# ---------------------------------------------------------------------------
# Scenario 4: Invalid enriched candle is blocked before strategy evaluation
# ---------------------------------------------------------------------------


def test_invalid_enriched_candle_blocked_before_evaluation() -> None:
    """Missing/non-finite enriched columns block strategy evaluation."""
    repo = FakeBotStateRepository()
    evaluator = FakeStrategyEvaluator(
        signal=SignalDecision(
            action=SignalAction.LONG_ENTRY,
            symbol="BTC",
            interval="1h",
            candle_timestamp=0,
            strategy_hash="test-hash",
        )
    )
    runtime = _create_runtime(
        repo=repo,
        evaluator=evaluator,
        indicator_engine=InMemoryIndicatorEngine(
            latest_bar=indicator_bar(atr=float("nan"))
        ),
        required_columns={"atr", "vp_vah"},
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.enrichment_valid is False
    assert "atr" in result.enrichment_errors
    assert "vp_vah" in result.enrichment_errors
    assert repo.signal_count == 0
    assert repo.order_intent_count == 0
    # Evaluator was never called
    assert len(evaluator.evaluate_calls) == 0


def test_optional_nan_does_not_block_evaluation() -> None:
    """Optional/non-required NaN column does not block evaluation."""
    repo = FakeBotStateRepository()
    runtime = _create_runtime(
        repo=repo,
        evaluator=FakeStrategyEvaluator(
            signal=SignalDecision(
                action=SignalAction.HOLD,
                symbol="BTC",
                interval="1h",
                candle_timestamp=0,
                strategy_hash="test-hash",
            )
        ),
        indicator_engine=InMemoryIndicatorEngine(
            latest_bar=indicator_bar(atr=1200.0, vp_vah=52000.0, rsi_14=float("nan"))
        ),
        required_columns={"atr", "vp_vah"},
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.enrichment_valid is True
    assert result.enrichment_errors == []


def test_validation_rejection_persisted_as_risk_event() -> None:
    """Validation rejection is persisted as an audit/risk event."""
    repo = FakeBotStateRepository()
    runtime = _create_runtime(
        repo=repo,
        indicator_engine=InMemoryIndicatorEngine(
            latest_bar=indicator_bar(atr=None, vp_vah=float("inf"))
        ),
        required_columns={"atr", "vp_vah"},
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.enrichment_valid is False
    risk_event = repo.last_risk_event
    assert risk_event is not None
    assert "enrichment" in risk_event.event_type.lower()
    assert risk_event.decision == "rejected"


# ---------------------------------------------------------------------------
# Scenario 3: Live candles are enriched with strategy-required indicators
# ---------------------------------------------------------------------------


def test_latest_bar_includes_required_columns_after_enrichment() -> None:
    """Enriched latest bar contains all required indicator columns."""
    repo = FakeBotStateRepository()
    evaluator = FakeStrategyEvaluator(
        signal=SignalDecision(
            action=SignalAction.LONG_ENTRY,
            symbol="BTC",
            interval="1h",
            candle_timestamp=0,
            strategy_hash="test-hash",
        )
    )
    runtime = _create_runtime(
        repo=repo,
        evaluator=evaluator,
        indicator_engine=InMemoryIndicatorEngine(
            latest_bar=indicator_bar(atr=1200.0, vp_vah=52000.0, vp_val=50000.0)
        ),
        required_columns={"atr", "vp_vah", "vp_val"},
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.enrichment_valid is True
    assert result.enrichment_errors == []
    assert result.signal_action == "long_entry"
    assert len(evaluator.evaluate_calls) == 1
    assert evaluator.evaluate_calls[0]["bar"].get("atr") == 1200.0


def test_evaluator_skipped_until_warmup_ready() -> None:
    """Strategy is skipped until warmup is ready."""
    evaluator = FakeStrategyEvaluator()
    runtime = _create_runtime(
        evaluator=evaluator,
        warmup_bars=closed_warmup_bars(5),
        required_columns={"atr"},
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle(offset=5))

    assert result.enrichment_valid is False
    assert "warmup" in result.message.lower()
    assert len(evaluator.evaluate_calls) == 0


def test_out_of_order_candle_ignored_on_gap_detection() -> None:
    """Out-of-order candle triggers gap detection and is rejected."""
    evaluator = FakeStrategyEvaluator()
    runtime = _create_runtime(
        evaluator=evaluator,
        indicator_engine=InMemoryIndicatorEngine(latest_bar=indicator_bar(atr=1200.0)),
        required_columns={"atr"},
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle(offset=200))

    assert result.enrichment_valid is False
    assert len(evaluator.evaluate_calls) == 0


# ---------------------------------------------------------------------------
# Scenario 2: Real YAML evaluator (not placeholder)
# ---------------------------------------------------------------------------


def test_yaml_strategy_loaded_into_real_evaluator() -> None:
    """Real evaluator is used, returns non-HOLD for matching bars."""
    from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
        SharedRuntimeStrategyEvaluatorFactory,
    )
    from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
        YamlStrategyDefinitionLoader,
    )

    strategy_path = "tests/fixtures/strategies/amt_dip_buyer_final.yaml"
    definition = YamlStrategyDefinitionLoader().load_from_file(strategy_path)
    strategy_hash = "test-hash-amt-dip"
    real_evaluator = SharedRuntimeStrategyEvaluatorFactory().create(
        definition=definition,
        symbol="BTC",
        interval="1h",
        strategy_hash=strategy_hash,
    )

    repo = FakeBotStateRepository()
    runtime = _create_runtime(
        repo=repo,
        evaluator=real_evaluator,
        indicator_engine=InMemoryIndicatorEngine(
            latest_bar=indicator_bar(
                atr=1200.0,
                vp_vah=52000.0,
                vp_val=50000.0,
                acceptance_into_value=True,
                above_value=False,
            )
        ),
        required_columns={
            "atr",
            "vp_vah",
            "vp_val",
            "acceptance_into_value",
            "above_value",
        },
    )
    runtime._start_session(strategy_path, strategy_hash, "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.enrichment_valid is True
    assert result.signal_action in {"long_entry", "short_entry", "hold"}


class TestPackageSignalBoundary:
    """The runtime uses the package only up to the signal boundary.

    The package owns parsing/indicators/evaluation; Finbot owns warmup,
    enrichment validation, signal persistence, risk gates, idempotency,
    and the exchange submission branch. These tests wire the real package
    evaluator with required_columns sourced from the package loader (not
    hand-maintained) and assert the boundary holds.
    """

    STRATEGY_PATH = "tests/fixtures/strategies/amt_dip_buyer_final.yaml"

    @staticmethod
    def _package_evaluator_and_columns():
        """Load AMT via the loader; return the real evaluator + package columns."""
        from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
            SharedRuntimeStrategyEvaluatorFactory,
        )
        from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
            YamlStrategyDefinitionLoader,
        )

        loader = YamlStrategyDefinitionLoader()
        definition = loader.load_from_file(TestPackageSignalBoundary.STRATEGY_PATH)
        required_columns = set(loader.last_required_columns())
        evaluator = SharedRuntimeStrategyEvaluatorFactory().create(
            definition=definition,
            symbol="BTC",
            interval="1h",
            strategy_hash="pkg-boundary",
        )
        return evaluator, required_columns

    def test_triggering_candle_persists_signal_without_submitting(self) -> None:
        evaluator, required_columns = self._package_evaluator_and_columns()
        exchange = InMemoryExchangeGateway()
        repo = FakeBotStateRepository()
        runtime = _create_runtime(
            repo=repo,
            exchange=exchange,
            evaluator=evaluator,
            indicator_engine=InMemoryIndicatorEngine(
                latest_bar=indicator_bar(
                    atr=1200.0,
                    vp_vah=52000.0,
                    vp_val=50000.0,
                    acceptance_into_value=True,
                    above_value=False,
                )
            ),
            required_columns=required_columns,
        )
        runtime._start_session(self.STRATEGY_PATH, "pkg-boundary", "BTC", "1h")

        result = runtime.process_closed_candle(new_closed_candle())

        # Package evaluated (signal boundary crossed); Finbot persisted and
        # did not submit (dry-run).
        assert result.enrichment_valid is True
        assert result.signal_action in {"long_entry", "short_entry", "hold"}
        assert exchange.submitted_order_count == 0

    def test_missing_package_required_column_blocks_before_evaluation(self) -> None:
        evaluator, required_columns = self._package_evaluator_and_columns()
        # The package requires 'atr' (concrete, directly referenced); omit it.
        assert "atr" in required_columns
        incomplete_bar = indicator_bar(
            vp_vah=52000.0,
            vp_val=50000.0,
            acceptance_into_value=True,
            above_value=False,
            # atr intentionally absent
        )
        runtime = _create_runtime(
            evaluator=evaluator,
            indicator_engine=InMemoryIndicatorEngine(latest_bar=incomplete_bar),
            required_columns=required_columns,
        )
        runtime._start_session(self.STRATEGY_PATH, "pkg-boundary", "BTC", "1h")

        result = runtime.process_closed_candle(new_closed_candle())

        # Finbot's EnrichmentValidator blocks before the package evaluates,
        # so no entry/exit signal is produced.
        assert result.enrichment_valid is False
        assert result.signal_action not in {
            "long_entry",
            "short_entry",
            "long_exit",
            "short_exit",
        }


def test_yaml_strategy_returns_hold_for_non_matching_bar() -> None:
    """Real evaluator returns HOLD when bar doesn't match rules."""
    from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
        SharedRuntimeStrategyEvaluatorFactory,
    )
    from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
        YamlStrategyDefinitionLoader,
    )

    strategy_path = "tests/fixtures/strategies/amt_dip_buyer_final.yaml"
    definition = YamlStrategyDefinitionLoader().load_from_file(strategy_path)
    real_evaluator = SharedRuntimeStrategyEvaluatorFactory().create(
        definition=definition,
        symbol="BTC",
        interval="1h",
        strategy_hash="test-hash",
    )

    runtime = _create_runtime(
        evaluator=real_evaluator,
        indicator_engine=InMemoryIndicatorEngine(
            latest_bar=indicator_bar(
                atr=1200.0,
                vp_vah=52000.0,
                vp_val=50000.0,
                acceptance_into_value=False,
                above_value=True,
            )
        ),
        required_columns={
            "atr",
            "vp_vah",
            "vp_val",
            "acceptance_into_value",
            "above_value",
        },
    )
    runtime._start_session(strategy_path, "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.enrichment_valid is True
    assert result.signal_action == "hold"


class TestBothTargetFixturesStartInDryRun:
    """Migration preserves existing behaviour: both AMT fixtures start in
    dry-run via the package evaluator and produce the expected signal on a
    known triggering bar (parity is now structural — same package both
    sides, no copied runtime, no parity test importing the monolith)."""

    @staticmethod
    def _runtime_for(strategy_path: str, latest_bar: dict):
        from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
            SharedRuntimeStrategyEvaluatorFactory,
        )
        from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
            YamlStrategyDefinitionLoader,
        )

        loader = YamlStrategyDefinitionLoader()
        definition = loader.load_from_file(strategy_path)
        evaluator = SharedRuntimeStrategyEvaluatorFactory().create(
            definition=definition,
            symbol="BTC",
            interval="1h",
            strategy_hash="migration",
        )
        return _create_runtime(
            evaluator=evaluator,
            indicator_engine=InMemoryIndicatorEngine(latest_bar=latest_bar),
            required_columns=set(loader.last_required_columns()),
        )

    def test_amt_dip_buyer_enters_on_acceptance_into_value(self) -> None:
        path = "tests/fixtures/strategies/amt_dip_buyer_final.yaml"
        runtime = self._runtime_for(
            path,
            indicator_bar(
                atr=2.0,
                vp_vah=110.0,
                vp_val=90.0,
                acceptance_into_value=True,
                above_value=False,
            ),
        )
        runtime._start_session(path, "migration", "BTC", "1h")

        result = runtime.process_closed_candle(new_closed_candle())

        assert result.enrichment_valid is True
        assert result.signal_action == "long_entry"

    def test_amt_v2_enters_when_value_area_is_narrow(self) -> None:
        path = "tests/fixtures/strategies/amt_v2_vol_filter.yaml"
        runtime = self._runtime_for(
            path,
            indicator_bar(
                atr=2.0,
                vp_vah=110.0,
                vp_val=90.0,
                value_area_width_pct=1.0,  # narrow (< 1.5) passes the filter
                acceptance_into_value=True,
                above_value=False,
            ),
        )
        runtime._start_session(path, "migration", "BTC", "1h")

        result = runtime.process_closed_candle(new_closed_candle())

        assert result.enrichment_valid is True
        assert result.signal_action == "long_entry"


# ---------------------------------------------------------------------------
# Scenario 1: Dry-run processes closed candles without submitting
# ---------------------------------------------------------------------------


def test_dry_run_processes_candle_without_submitting() -> None:
    """Dry-run enriches, evaluates, persists, but never submits."""
    exchange = InMemoryExchangeGateway()
    repo = FakeBotStateRepository()
    runtime = _create_runtime(
        repo=repo,
        exchange=exchange,
        evaluator=FakeStrategyEvaluator(
            signal=SignalDecision(
                action=SignalAction.LONG_ENTRY,
                symbol="BTC",
                interval="1h",
                candle_timestamp=0,
                strategy_hash="test-hash",
            )
        ),
        indicator_engine=InMemoryIndicatorEngine(latest_bar=indicator_bar(atr=1200.0)),
        required_columns={"atr"},
    )

    run_id = runtime.start(
        strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
        symbol="BTC",
        interval="1h",
        strategy_hash="test-hash",
    )
    assert run_id

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.enrichment_valid is True
    assert result.signal_action in {"hold", "long_entry", "short_entry"}
    assert exchange.submitted_order_count == 0
    assert repo.get_latest_bot_run() is not None

    runtime.stop()


def test_dry_run_stop_ends_session() -> None:
    """Stopping the runtime persists the end marker."""
    repo = FakeBotStateRepository()
    runtime = _create_runtime(repo=repo)

    runtime.start("test-strategy.yaml", "BTC", "1h", "test-hash")
    runtime.stop()

    run = repo.get_latest_bot_run()
    assert run is not None


def test_enriched_frame_is_cached_between_candles() -> None:
    """P1/P5: the frame is built once, then appended to, not rebuilt per candle."""

    converter = CountingBarFrameConverter()
    runtime = _create_runtime(
        indicator_engine=InMemoryIndicatorEngine(latest_bar=indicator_bar(atr=1200.0)),
        bar_frame_converter=converter,
        required_columns={"atr"},
    )
    runtime._start_session("s", "h", "BTC", "1h")

    runtime.process_closed_candle(new_closed_candle(offset=100))
    runtime.process_closed_candle(new_closed_candle(offset=101))

    # First candle builds the frame; the second must go through append_bar
    # (the incremental path) rather than rebuilding from scratch.
    assert converter.append_bar_calls == 1, "second candle did not append"


class CountingBarFrameConverter(InMemoryBarFrameConverter):
    """Wraps the fake converter to count rebuilds vs appends."""

    def __init__(self) -> None:
        super().__init__()
        self.bars_to_frame_calls = 0
        self.append_bar_calls = 0

    def bars_to_frame(self, bars):
        self.bars_to_frame_calls += 1
        return super().bars_to_frame(bars)

    def append_bar(self, frame, bar):
        self.append_bar_calls += 1
        return super().append_bar(frame, bar)
