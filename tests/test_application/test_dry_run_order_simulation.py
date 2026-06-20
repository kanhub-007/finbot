"""Tests for Slice 2 — dry-run position simulation and duplicate signal prevention."""

from decimal import Decimal

from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.services.enrichment_validator import (
    EnrichmentValidator,
)
from finbot.core.domain.services.order_planner import OrderPlanner
from finbot.core.domain.services.risk_gates.duplicate_signal_gate import (
    DuplicateSignalGate,
)
from finbot.core.domain.services.risk_gates.max_position_gate import (
    MaxPositionGate,
)
from finbot.core.domain.services.risk_gates.mode_gate import ModeGate
from tests.fakes import (
    FakeBotStateRepository,
    FakeStrategyEvaluator,
    InMemoryBarFrameConverter,
    InMemoryExchangeGateway,
    InMemoryIndicatorEngine,
    closed_warmup_bars,
    indicator_bar,
    make_dry_run_submission_strategy,
    make_event_emitter,
    new_closed_candle,
)

# ---------------------------------------------------------------------------
# TrackingDryRunExchange — exchange fake that simulates position changes
# ---------------------------------------------------------------------------


class TrackingDryRunExchange(InMemoryExchangeGateway):
    """Dry-run exchange that simulates position changes locally."""

    def __init__(self, symbol: str = "BTC") -> None:
        super().__init__()
        self._tracked_symbol = symbol
        self._position = PositionSnapshot(
            symbol=symbol, direction=PositionDirection.FLAT, size=Decimal("0")
        )

    def get_position(self, symbol: str) -> PositionSnapshot:
        return self._position

    def submit_order(self, intent) -> dict:
        self.submitted_order_count += 1
        if intent.side == OrderSide.BUY and not intent.reduce_only:
            new_size = self._position.size + intent.size
            direction = (
                PositionDirection.LONG if new_size > 0 else PositionDirection.FLAT
            )
            self._position = PositionSnapshot(
                symbol=self._tracked_symbol,
                direction=direction,
                size=new_size,
                entry_price=intent.limit_price,
            )
        elif intent.side == OrderSide.SELL and intent.reduce_only:
            new_size = max(Decimal("0"), self._position.size - intent.size)
            direction = (
                self._position.direction if new_size > 0 else PositionDirection.FLAT
            )
            self._position = PositionSnapshot(
                symbol=self._tracked_symbol,
                direction=direction,
                size=new_size,
                entry_price=self._position.entry_price,
            )
        return {"status": "dry_run_simulated"}


# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------


def _make_runtime(**overrides):
    """Build a LiveTradingRuntimeUseCase with sensible dry-run defaults."""
    from finbot.core.application.use_cases.live_trading_runtime import (
        LiveTradingRuntimeUseCase,
    )

    repo = overrides.get("state_repository") or FakeBotStateRepository()
    max_pos = overrides.get("_max_position", Decimal("100000"))

    kwargs = dict(
        exchange_gateway=TrackingDryRunExchange("BTC"),
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
        mode=TradingMode.DRY_RUN,
        submission_strategy=make_dry_run_submission_strategy(
            repo,
            exchange=overrides.get("exchange_gateway", TrackingDryRunExchange("BTC")),
        ),
        event_emitter=make_event_emitter(),
        warmup_bars=closed_warmup_bars(100),
        required_columns={"atr"},
        order_planner=OrderPlanner(
            gates=[
                ModeGate(),
                DuplicateSignalGate(repo),
                MaxPositionGate(max_notional_usd=max_pos),
            ]
        ),
    )
    # Apply overrides, filtering out internal-only keys
    for k, v in overrides.items():
        if not k.startswith("_"):
            kwargs[k] = v
    return LiveTradingRuntimeUseCase(**kwargs)


# ---------------------------------------------------------------------------
# Scenario: Dry-run simulates position state and prevents duplicate orders
# ---------------------------------------------------------------------------


def test_dry_run_accepts_signal_and_increments_position() -> None:
    """Dry-run: accepted signal creates order intent and updates position."""
    exchange = TrackingDryRunExchange("BTC")
    repo = FakeBotStateRepository()
    runtime = _make_runtime(exchange_gateway=exchange, state_repository=repo)
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.enrichment_valid is True
    assert result.signal_action == "long_entry"
    assert repo.order_intent_count == 1

    pos = exchange.get_position("BTC")
    assert pos.direction == PositionDirection.LONG
    assert pos.size > Decimal("0")


def test_dry_run_duplicate_signal_is_rejected() -> None:
    """Replaying same signal after restart is rejected as duplicate."""
    repo = FakeBotStateRepository()
    exchange = TrackingDryRunExchange("BTC")

    first_runtime = _make_runtime(state_repository=repo, exchange_gateway=exchange)
    first_runtime._start_session("test-strategy", "test-hash", "BTC", "1h")
    first_result = first_runtime.process_closed_candle(new_closed_candle())

    assert first_result.signal_action == "long_entry"
    first_intent_count = repo.order_intent_count
    assert first_intent_count == 1

    # Simulate restart: new runtime with same repository
    second_runtime = _make_runtime(state_repository=repo, exchange_gateway=exchange)
    second_runtime._start_session("test-strategy-2", "test-hash", "BTC", "1h")
    second_runtime.process_closed_candle(new_closed_candle())

    # Duplicate signal should be rejected — no new intent
    assert repo.order_intent_count == first_intent_count


def test_max_position_exceeded_rejects_entry() -> None:
    """Max position exceeded -> risk rejected, no intent saved."""
    repo = FakeBotStateRepository()
    runtime = _make_runtime(state_repository=repo, _max_position=Decimal("1"))
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.signal_action == "long_entry"
    assert repo.order_intent_count == 0


def test_hold_signal_creates_no_order_intent() -> None:
    """HOLD signal creates no order intent."""
    repo = FakeBotStateRepository()
    runtime = _make_runtime(
        state_repository=repo,
        strategy_evaluator=FakeStrategyEvaluator(
            signal=SignalDecision(
                action=SignalAction.HOLD,
                symbol="BTC",
                interval="1h",
                candle_timestamp=1735689600,
                strategy_hash="test-hash",
            )
        ),
    )
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.signal_action == "hold"
    assert repo.order_intent_count == 0


def test_processed_signal_key_is_persisted() -> None:
    """After a successful signal, the signal key is marked as processed."""
    repo = FakeBotStateRepository()
    runtime = _make_runtime(state_repository=repo)
    runtime._start_session("test-strategy", "test-hash", "BTC", "1h")

    result = runtime.process_closed_candle(new_closed_candle())

    assert result.signal_action == "long_entry"
    assert repo.count_signals() == 1
    signal = repo.get_last_signal()
    assert signal is not None
    assert "BTC" in signal.signal_key
