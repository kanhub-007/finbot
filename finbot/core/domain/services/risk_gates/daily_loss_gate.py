"""Daily loss gate — rejects when cumulative loss exceeds the daily cap."""

from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.risk_gate import RiskGate


class DailyLossGate(RiskGate):
    """Reject when realized + unrealized loss exceeds *max_loss_usd*."""

    def __init__(self, max_loss_usd: Decimal = Decimal("0")) -> None:
        self._max = max_loss_usd

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        if self._max <= 0:
            return RiskDecision(accepted=True, gate_name="daily_loss")
        daily = context.get("daily_loss_usd", Decimal("0"))
        if daily >= self._max:
            return RiskDecision(
                accepted=False,
                reason=f"Daily loss {daily} >= max {self._max}",
                gate_name="daily_loss",
            )
        return RiskDecision(accepted=True, gate_name="daily_loss")
