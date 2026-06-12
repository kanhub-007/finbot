"""Stale data gate — rejects signals when market data is too old."""

from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.risk_gate import RiskGate


class StaleDataGate(RiskGate):
    """Reject a signal when the bar timestamp is older than *max_age_seconds*."""

    def __init__(self, max_age_seconds: float = 120) -> None:
        self._max_age = max_age_seconds

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        import time

        bar = context.get("bar", {})
        bar_ts = bar.get("timestamp", 0)
        if isinstance(bar_ts, int) and bar_ts > 0:
            age = time.time() - bar_ts
            if age > self._max_age:
                return RiskDecision(
                    accepted=False,
                    reason=f"Bar age {age:.0f}s exceeds {self._max_age}s",
                    gate_name="stale_data",
                )
        return RiskDecision(accepted=True, gate_name="stale_data")
