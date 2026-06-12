"""Tests for OrderPlanner and risk gates."""

from decimal import Decimal

from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.services.order_planner import OrderPlanner
from finbot.core.domain.services.risk_gates.daily_loss_gate import (
    DailyLossGate,
)
from finbot.core.domain.services.risk_gates.duplicate_signal_gate import (
    DuplicateSignalGate,
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
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)


def _signal(action: SignalAction) -> SignalDecision:
    return SignalDecision(
        action=action,
        symbol="BTC",
        interval="1h",
        candle_timestamp=1,
        strategy_hash="t",
    )


def _context(**kwargs) -> dict:
    ctx: dict = {"bar": {"close": 50000, "timestamp": 9999999999}, "symbol": "BTC"}
    ctx.update(kwargs)
    return ctx


class TestOrderPlanner:
    def test_buy_signal_creates_long_entry_intent(self) -> None:
        planner = OrderPlanner(gates=[ModeGate()])
        result = planner.plan(_signal(SignalAction.LONG_ENTRY), _context())
        assert result.accepted
        assert result.intent is not None
        assert result.intent.side == OrderSide.BUY
        assert result.intent.reduce_only is False

    def test_exit_signal_creates_reduce_only_intent(self) -> None:
        planner = OrderPlanner(gates=[ModeGate()])
        result = planner.plan(_signal(SignalAction.LONG_EXIT), _context())
        assert result.accepted
        assert result.intent is not None
        assert result.intent.side == OrderSide.SELL
        assert result.intent.reduce_only is True

    def test_hold_signal_returns_no_intent(self) -> None:
        planner = OrderPlanner(gates=[ModeGate()])
        result = planner.plan(_signal(SignalAction.HOLD), _context())
        assert result.accepted
        assert result.intent is None


class TestDuplicateSignalGate:
    def test_duplicate_signal_is_rejected(self) -> None:
        repo = InMemoryBotStateRepository()
        repo.mark_signal_processed(
            ProcessedSignal(
                signal_key="BTC:1h:1:t",
                bot_run_id="r1",
                signal_action="long_entry",
                bar_timestamp="2025-01-01T09:00",
            )
        )
        planner = OrderPlanner(gates=[DuplicateSignalGate(repo)])
        result = planner.plan(_signal(SignalAction.LONG_ENTRY), _context())
        assert not result.accepted
        assert result.gate_name == "duplicate_signal"

    def test_new_signal_passes(self) -> None:
        repo = InMemoryBotStateRepository()
        planner = OrderPlanner(gates=[DuplicateSignalGate(repo)])
        result = planner.plan(_signal(SignalAction.LONG_ENTRY), _context())
        assert result.accepted


class TestStaleDataGate:
    def test_stale_data_is_rejected(self) -> None:
        gate = StaleDataGate(max_age_seconds=60)
        result = gate.check(
            _signal(SignalAction.LONG_ENTRY),
            {"bar": {"timestamp": 1}},  # very old
        )
        assert not result.accepted
        assert result.gate_name == "stale_data"

    def test_fresh_data_passes(self) -> None:
        import time

        gate = StaleDataGate(max_age_seconds=60)
        result = gate.check(
            _signal(SignalAction.LONG_ENTRY),
            {"bar": {"timestamp": int(time.time() - 30)}},
        )
        assert result.accepted


class TestMaxPositionGate:
    def test_oversized_position_is_rejected(self) -> None:
        planner = OrderPlanner(gates=[MaxPositionGate(max_notional_usd=Decimal("100"))])
        result = planner.plan(
            _signal(SignalAction.LONG_ENTRY),
            _context(proposed_size=Decimal("1")),
        )
        assert not result.accepted
        assert result.gate_name == "max_position"

    def test_small_position_passes(self) -> None:
        planner = OrderPlanner(
            gates=[MaxPositionGate(max_notional_usd=Decimal("100000"))]
        )
        result = planner.plan(
            _signal(SignalAction.LONG_ENTRY),
            _context(proposed_size=Decimal("0.001")),
        )
        assert result.accepted


class TestMaxOpenOrdersGate:
    def test_max_open_orders_is_enforced(self) -> None:
        gate = MaxOpenOrdersGate(max_orders=3)
        result = gate.check(_signal(SignalAction.LONG_ENTRY), {"open_order_count": 3})
        assert not result.accepted
        assert result.gate_name == "max_open_orders"

    def test_under_limit_passes(self) -> None:
        gate = MaxOpenOrdersGate(max_orders=3)
        result = gate.check(_signal(SignalAction.LONG_ENTRY), {"open_order_count": 2})
        assert result.accepted


class TestDailyLossGate:
    def test_daily_loss_limit_is_enforced(self) -> None:
        gate = DailyLossGate(max_loss_usd=Decimal("100"))
        result = gate.check(
            _signal(SignalAction.LONG_ENTRY),
            {"daily_loss_usd": Decimal("100")},
        )
        assert not result.accepted
        assert result.gate_name == "daily_loss"

    def test_below_limit_passes(self) -> None:
        gate = DailyLossGate(max_loss_usd=Decimal("100"))
        result = gate.check(
            _signal(SignalAction.LONG_ENTRY),
            {"daily_loss_usd": Decimal("50")},
        )
        assert result.accepted


class TestReduceOnlyGate:
    def test_exit_without_reduce_only_is_rejected(self) -> None:
        gate = ReduceOnlyGate()
        result = gate.check(_signal(SignalAction.LONG_EXIT), {"reduce_only": False})
        assert not result.accepted
        assert result.gate_name == "reduce_only"

    def test_entry_passes_reduce_only_gate(self) -> None:
        gate = ReduceOnlyGate()
        result = gate.check(_signal(SignalAction.LONG_ENTRY), {})
        assert result.accepted

    def test_exit_with_reduce_only_passes(self) -> None:
        gate = ReduceOnlyGate()
        result = gate.check(_signal(SignalAction.LONG_EXIT), {"reduce_only": True})
        assert result.accepted
