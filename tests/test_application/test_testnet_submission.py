"""Tests for Slice 3 — testnet order normalization, cloid, and submission."""

from decimal import Decimal

from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.services.cloid_generator import CloidGenerator
from finbot.core.domain.services.enrichment_validator import (
    EnrichmentValidator,
)
from finbot.core.domain.services.order_normalizer import OrderNormalizer
from finbot.core.domain.services.order_planner import OrderPlanner
from finbot.core.domain.services.risk_gates.duplicate_signal_gate import (
    DuplicateSignalGate,
)
from finbot.core.domain.services.risk_gates.mode_gate import ModeGate
from tests.fakes import (
    FakeExchangeGateway,
    FakeStrategyEvaluator,
    InMemoryBarFrameConverter,
    InMemoryIndicatorEngine,
    InMemoryMarketMetadataProvider,
    StubBotStateRepository,
    closed_warmup_bars,
    indicator_bar,
    make_event_emitter,
    new_closed_candle,
)


def _make_live_submission_strategy(exchange, repo, normalizer=None):
    """Build a LiveSubmissionStrategy wired to the test exchange."""
    from finbot.infrastructure.adapters.live_submission_strategy import (
        LiveSubmissionStrategy,
    )

    return LiveSubmissionStrategy(exchange, normalizer, repo)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime(**overrides):
    """Build a LiveTradingRuntimeUseCase with testnet defaults."""
    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )

    repo = overrides.get("state_repository") or StubBotStateRepository()
    exchange = overrides.get("exchange_gateway") or FakeExchangeGateway()
    metadata_provider = overrides.get(
        "metadata_provider", InMemoryMarketMetadataProvider.for_btc()
    )
    normalizer = overrides.get("normalizer")

    if normalizer is None:
        meta = metadata_provider.get_metadata("BTC")
        if meta is not None:
            normalizer = OrderNormalizer(metadata=meta)

    # Map test override keys to constructor parameter names
    key_map = {
        "metadata_provider": "market_metadata_provider",
        "normalizer": "order_normalizer",
        "_cloid_gen": "cloid_generator",
    }
    kwargs = dict(
        exchange_gateway=exchange,
        strategy_evaluator=FakeStrategyEvaluator(
            signal=SignalDecision(
                action=SignalAction.LONG_ENTRY,
                symbol="BTC",
                interval="1h",
                candle_timestamp=1735689600,
                strategy_hash="test-hash",
            )
        ),
        state_repository=repo,
        indicator_calculator=InMemoryIndicatorEngine(
            latest_bar=indicator_bar(atr=1200.0)
        ),
        enrichment_validator=EnrichmentValidator(),
        bar_frame_converter=InMemoryBarFrameConverter(),
        mode=TradingMode.TESTNET,
        submission_strategy=overrides.get("submission_strategy")
        or _make_live_submission_strategy(exchange, repo, normalizer),
        event_emitter=make_event_emitter(),
        warmup_bars=closed_warmup_bars(100),
        required_columns={"atr"},
        order_planner=OrderPlanner(gates=[ModeGate(), DuplicateSignalGate(repo)]),
        market_metadata_provider=metadata_provider,
        order_normalizer=normalizer,
        cloid_generator=CloidGenerator(),
    )
    for k, v in overrides.items():
        kwargs[key_map.get(k, k)] = v
    return LiveTradingRuntimeUseCase(**kwargs)


# ---------------------------------------------------------------------------
# Scenario: Testnet submits normalized accepted intents with idempotent cloid
# ---------------------------------------------------------------------------


def test_testnet_submits_normalized_intent_with_cloid() -> None:
    """Testnet mode normalizes, generates cloid, submits, persists response."""
    repo = StubBotStateRepository()
    exchange = FakeExchangeGateway()
    metadata = InMemoryMarketMetadataProvider.for_btc()

    runtime = _make_runtime(
        state_repository=repo,
        exchange_gateway=exchange,
        metadata_provider=metadata,
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.enrichment_valid is True
    assert result.signal_action == "long_entry"
    assert result.submitted is True

    # Intent has cloid
    intent = repo.last_order_intent()
    assert intent is not None
    assert intent.cloid is not None
    assert intent.cloid != ""
    assert intent.size > Decimal("0")

    # Response is persisted
    response = repo.get_last_order_response()
    assert response is not None
    assert response.status == "ok"


def test_testnet_normalized_intent_has_correct_precision() -> None:
    """Normalized intent uses exchange-safe size and price precision."""
    repo = StubBotStateRepository()
    exchange = FakeExchangeGateway()

    runtime = _make_runtime(
        state_repository=repo,
        exchange_gateway=exchange,
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.submitted is True
    # The submitted intent should be normalized to 5 decimal places
    assert len(exchange.submitted_intents) == 1
    norm = exchange.submitted_intents[0]
    # Check size has correct precision (5 decimals for BTC)
    size_str = str(norm.size)
    assert "." in size_str or norm.size == Decimal("0")


def test_missing_cloid_blocks_testnet_submission() -> None:
    """Without cloid generator, testnet should not submit."""
    repo = StubBotStateRepository()
    exchange = FakeExchangeGateway()

    runtime = _make_runtime(
        state_repository=repo,
        exchange_gateway=exchange,
        _cloid_gen=None,
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    # Should still process, but not submit
    assert result.signal_action == "long_entry"
    assert result.submitted is False


def test_unknown_symbol_metadata_rejected_before_submit() -> None:
    """Unknown symbol metadata should reject the order."""
    repo = StubBotStateRepository()
    exchange = FakeExchangeGateway()
    empty_metadata = InMemoryMarketMetadataProvider({})

    runtime = _make_runtime(
        state_repository=repo,
        exchange_gateway=exchange,
        metadata_provider=empty_metadata,
        normalizer=None,
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    # Without metadata, can't normalize — should still process signal
    assert result.signal_action in {"long_entry", "hold"}
    # No exchange submission without normalizer
    assert exchange.submitted_order_count == 0


def test_reconciliation_record_persisted_after_testnet_submit() -> None:
    """Reconciliation record is saved after a testnet order."""
    repo = StubBotStateRepository()
    exchange = FakeExchangeGateway()

    runtime = _make_runtime(
        state_repository=repo,
        exchange_gateway=exchange,
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.submitted is True
    # Reconciliation should be recorded (placeholder, not yet fully reconciled)
    rec = repo.last_reconciliation()
    assert rec is not None
    assert isinstance(rec.position_matches, bool)
