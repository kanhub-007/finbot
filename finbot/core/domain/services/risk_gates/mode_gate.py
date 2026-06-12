"""Mode gate — blocks order planning when mode does not allow trading."""

from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.risk_gate import RiskGate


class ModeGate(RiskGate):
    """Reject signals unless mode is explicitly permissioned.

    For now all modes pass; live-mode guard is in Phase 16.
    """

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        _ = signal, context
        return RiskDecision(accepted=True, gate_name="mode")
