"""Max position gate — rejects entries that exceed the notional cap."""

from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.risk_gate import RiskGate


class MaxPositionGate(RiskGate):
    """Reject entry signals when position would exceed *max_notional_usd*."""

    def __init__(self, max_notional_usd: Decimal = Decimal("0")) -> None:
        self._max = max_notional_usd

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        if self._max <= 0:
            return RiskDecision(accepted=True, gate_name="max_position")

        if signal.action not in (
            SignalAction.LONG_ENTRY,
            SignalAction.SHORT_ENTRY,
        ):
            return RiskDecision(accepted=True, gate_name="max_position")

        bar = context.get("bar", {})
        close = float(bar.get("close", 0))
        size = Decimal(str(context.get("proposed_size", 1)))
        notional = size * Decimal(str(close))

        if notional > self._max:
            return RiskDecision(
                accepted=False,
                reason=f"Notional {notional} > max {self._max}",
                gate_name="max_position",
            )
        return RiskDecision(accepted=True, gate_name="max_position")
