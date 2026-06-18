"""Tests for manual-order risk gates — Classical school, black-box.

Manual orders (/long, /short) pass through a dedicated gate chain separate
from strategy gates (which operate on SignalDecision). These gates take an
OrderIntent + context and return a RiskDecision.
"""

from decimal import Decimal

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.runtime_bot_config import RuntimeBotConfig
from finbot.core.domain.services.risk_gates.manual_max_position_gate import (
    ManualMaxPositionGate,
)
from finbot.core.domain.services.risk_gates.manual_mode_gate import ManualModeGate


def _buy_intent(symbol: str = "BTC", size: str = "0.01") -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=OrderSide.BUY,
        size=Decimal(size),
        order_type=OrderType.MARKET,
    )


class TestManualMaxPositionGate:
    """ManualMaxPositionGate checks notional vs RuntimeBotConfig limit."""

    def test_accepts_when_notional_under_limit(self):
        cfg = RuntimeBotConfig()
        cfg.set("max_position", "1000")
        gate = ManualMaxPositionGate(cfg)

        # 0.01 BTC @ 50000 = 500 USD notional < 1000 limit
        decision = gate.check(
            _buy_intent(size="0.01"),
            {"price": Decimal("50000")},
        )

        assert decision.accepted is True

    def test_rejects_when_notional_over_limit(self):
        cfg = RuntimeBotConfig()
        cfg.set("max_position", "100")
        gate = ManualMaxPositionGate(cfg)

        # 0.01 BTC @ 50000 = 500 USD notional > 100 limit
        decision = gate.check(
            _buy_intent(size="0.01"),
            {"price": Decimal("50000")},
        )

        assert decision.accepted is False
        assert "100" in decision.reason
        assert decision.gate_name == "manual_max_position"

    def test_accepts_when_limit_disabled(self):
        """max_position=0 disables the gate."""
        cfg = RuntimeBotConfig()
        cfg.set("max_position", "0")
        gate = ManualMaxPositionGate(cfg)

        decision = gate.check(
            _buy_intent(size="100"),
            {"price": Decimal("50000")},
        )

        assert decision.accepted is True

    def test_uses_runtime_config_changes_immediately(self):
        """Lowering the limit blocks subsequent orders."""
        cfg = RuntimeBotConfig()
        cfg.set("max_position", "1000")
        gate = ManualMaxPositionGate(cfg)

        assert gate.check(_buy_intent(size="0.01"), {"price": Decimal("50000")}).accepted

        cfg.set("max_position", "100")  # lower to 100

        decision = gate.check(_buy_intent(size="0.01"), {"price": Decimal("50000")})
        assert decision.accepted is False


class TestManualModeGate:
    """ManualModeGate blocks manual orders when mode is misconfigured."""

    def test_accepts_dry_run(self):
        gate = ManualModeGate(mode="dry_run", live_trading_ack=False)
        assert gate.check(_buy_intent(), {}).accepted is True

    def test_accepts_live_with_ack(self):
        gate = ManualModeGate(mode="live", live_trading_ack=True)
        assert gate.check(_buy_intent(), {}).accepted is True

    def test_rejects_live_without_ack(self):
        gate = ManualModeGate(mode="live", live_trading_ack=False)
        decision = gate.check(_buy_intent(), {})
        assert decision.accepted is False
        assert decision.gate_name == "manual_mode"
