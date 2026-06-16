"""Tests for DailyLossGate with realized PnL (Scenarios S5, S6).

Classical school: real DailyLossGate, real risk context dict.
No mocks — assert on RiskDecision outcomes.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.entities.trade import Trade
from finbot.core.domain.services.risk_gates.daily_loss_gate import (
    DailyLossGate,
)
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _entry_signal() -> SignalDecision:
    return SignalDecision(
        action=SignalAction.LONG_ENTRY,
        symbol="BTC",
        interval="1h",
        candle_timestamp=1,
        strategy_hash="test",
    )


def _exit_signal(action: SignalAction = SignalAction.LONG_EXIT) -> SignalDecision:
    return SignalDecision(
        action=action,
        symbol="BTC",
        interval="1h",
        candle_timestamp=1,
        strategy_hash="test",
    )


# -- Scenario S5: DailyLossGate rejects when realized loss exceeds cap --------


class TestDailyLossGateRejects:
    def test_rejects_when_realized_loss_exceeds_cap(self) -> None:
        """S5: realized -30 loss > cap 25 → rejected."""
        repo = InMemoryBotStateRepository()
        gate = DailyLossGate(max_loss_usd=Decimal("25"))

        today = _now().date()

        # Seed a closed losing trade realized today.
        trade = Trade(
            position_id="p1",
            bot_run_id="run1",
            symbol="BTC",
            side=PositionDirection.LONG,
            size=Decimal("0"),
            entry_price=Decimal("50000"),
            opened_at=_now() - timedelta(hours=2),
            status="closed",
            realized_pnl=Decimal("-30"),
            total_fee=Decimal("1"),
            closed_at=_now(),
            close_price=Decimal("47000"),
        )
        repo.open_trade(trade)

        loss = repo.realized_loss_on(today)
        assert loss == Decimal("30")  # abs value
        ctx = {"daily_loss_usd": loss}
        decision = gate.check(_entry_signal(), ctx)

        assert decision.accepted is False
        assert decision.gate_name == "daily_loss"
        assert "Daily loss" in decision.reason or "30" in decision.reason

    def test_accepts_when_under_cap(self) -> None:
        """S5: realized -20 loss < cap 25 → accepted."""
        repo = InMemoryBotStateRepository()
        gate = DailyLossGate(max_loss_usd=Decimal("25"))

        trade = Trade(
            position_id="p1",
            bot_run_id="run1",
            symbol="BTC",
            side=PositionDirection.LONG,
            size=Decimal("0"),
            entry_price=Decimal("50000"),
            opened_at=_now() - timedelta(hours=2),
            status="closed",
            realized_pnl=Decimal("-20"),
            total_fee=Decimal("1"),
            closed_at=_now(),
            close_price=Decimal("48000"),
        )
        repo.open_trade(trade)

        ctx = {"daily_loss_usd": repo.realized_loss_on(_now().date())}
        decision = gate.check(_entry_signal(), ctx)

        assert decision.accepted is True

    def test_zero_loss_today_accepted(self) -> None:
        """No closed losing trades today → daily_loss_usd=0 → accepted."""
        gate = DailyLossGate(max_loss_usd=Decimal("25"))
        ctx = {"daily_loss_usd": Decimal("0")}
        decision = gate.check(_entry_signal(), ctx)
        assert decision.accepted is True

    def test_yesterdays_loss_excluded_today(self) -> None:
        """S6: loss yesterday, but zero today → accepted."""
        repo = InMemoryBotStateRepository()
        gate = DailyLossGate(max_loss_usd=Decimal("25"))

        yesterday = _now() - timedelta(days=1)
        trade = Trade(
            position_id="p1",
            bot_run_id="run1",
            symbol="BTC",
            side=PositionDirection.LONG,
            size=Decimal("0"),
            entry_price=Decimal("50000"),
            opened_at=yesterday - timedelta(hours=1),
            status="closed",
            realized_pnl=Decimal("-100"),
            total_fee=Decimal("1"),
            closed_at=yesterday,
            close_price=Decimal("49000"),
        )
        repo.open_trade(trade)

        loss_today = repo.realized_loss_on(_now().date())
        assert loss_today == Decimal("0")
        ctx = {"daily_loss_usd": loss_today}
        decision = gate.check(_entry_signal(), ctx)
        assert decision.accepted is True

    def test_gate_bypassed_when_max_zero(self) -> None:
        """Gate with max_loss_usd <= 0 always accepts."""
        gate = DailyLossGate(max_loss_usd=Decimal("0"))
        ctx = {"daily_loss_usd": Decimal("-100")}
        decision = gate.check(_entry_signal(), ctx)
        assert decision.accepted is True


# -- Exit bypass: exit signals always pass the daily-loss gate ----------------


class TestDailyLossGateExitBypass:
    def test_long_exit_accepted_when_over_cap(self) -> None:
        """Exit signals bypass the daily-loss cap regardless of loss."""
        gate = DailyLossGate(max_loss_usd=Decimal("25"))
        ctx = {"daily_loss_usd": Decimal("100")}
        decision = gate.check(_exit_signal(SignalAction.LONG_EXIT), ctx)
        assert decision.accepted is True

    def test_short_exit_accepted_when_over_cap(self) -> None:
        """SHORT_EXIT also bypasses the cap."""
        gate = DailyLossGate(max_loss_usd=Decimal("25"))
        ctx = {"daily_loss_usd": Decimal("100")}
        decision = gate.check(_exit_signal(SignalAction.SHORT_EXIT), ctx)
        assert decision.accepted is True

    def test_entry_still_rejected_when_over_cap(self) -> None:
        """LONG_ENTRY is NOT bypassed — still blocked when over cap."""
        gate = DailyLossGate(max_loss_usd=Decimal("25"))
        ctx = {"daily_loss_usd": Decimal("100")}
        decision = gate.check(_entry_signal(), ctx)
        assert decision.accepted is False
