"""Max leverage gate — rejects orders that exceed the configured leverage cap."""

from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.risk_gate import RiskGate


class MaxLeverageGate(RiskGate):
    """Reject entries whose effective leverage exceeds *max_leverage*.

    The effective leverage is read from ``context["leverage"]``.  When no
    leverage is supplied it defaults to ``1`` (an unleveraged / cash-sized
    position), which is safe for the spot-sized strategies Finbot currently
    runs.  As with the other numeric gates, ``max_leverage <= 0`` disables
    the check entirely.
    """

    def __init__(self, max_leverage: int = 0) -> None:
        self._max = max_leverage

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        if self._max <= 0:
            return RiskDecision(accepted=True, gate_name="max_leverage")
        leverage = context.get("leverage", 1)
        if leverage > self._max:
            return RiskDecision(
                accepted=False,
                reason=f"Leverage {leverage} > max {self._max}",
                gate_name="max_leverage",
            )
        return RiskDecision(accepted=True, gate_name="max_leverage")
