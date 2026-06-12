"""Max open orders gate — rejects when too many orders are outstanding."""

from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.risk_gate import RiskGate


class MaxOpenOrdersGate(RiskGate):
    """Reject when open order count reaches *max_orders*."""

    def __init__(self, max_orders: int = 0) -> None:
        self._max = max_orders

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        if self._max <= 0:
            return RiskDecision(accepted=True, gate_name="max_open_orders")
        current = context.get("open_order_count", 0)
        if current >= self._max:
            return RiskDecision(
                accepted=False,
                reason=f"Open orders {current} >= max {self._max}",
                gate_name="max_open_orders",
            )
        return RiskDecision(accepted=True, gate_name="max_open_orders")
