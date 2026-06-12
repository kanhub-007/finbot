"""Max leverage gate — placeholder for leverage enforcement."""

from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.risk_gate import RiskGate


class MaxLeverageGate(RiskGate):
    """Accept all signals for now — leverage enforcement deferred."""

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        _ = signal, context
        return RiskDecision(accepted=True, gate_name="max_leverage")
