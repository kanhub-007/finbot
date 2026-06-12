"""Reduce-only exit gate — ensures exit orders are marked reduce_only."""

from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.risk_gate import RiskGate


class ReduceOnlyGate(RiskGate):
    """Force reduce_only=True on all exit orders.

    Entries pass through; exits that are not already reduce_only
    are rejected with instructions to set the flag.
    """

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        if signal.action in (
            SignalAction.LONG_EXIT,
            SignalAction.SHORT_EXIT,
        ):
            existing = context.get("reduce_only", False)
            if not existing:
                return RiskDecision(
                    accepted=False,
                    reason="Exit order must be reduce_only",
                    gate_name="reduce_only",
                )
        return RiskDecision(accepted=True, gate_name="reduce_only")
