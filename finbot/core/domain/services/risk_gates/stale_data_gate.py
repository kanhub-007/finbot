"""Stale data gate — rejects signals when market data is too old."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.risk_gate import RiskGate


class StaleDataGate(RiskGate):
    """Reject a signal when the bar timestamp is older than *max_age_seconds*.

    The clock is injectable (defaults to ``time.time``) so the gate stays a
    pure, testable domain service with no hidden environment dependency.
    """

    def __init__(
        self,
        max_age_seconds: float = 120,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._max_age = max_age_seconds
        self._now = now

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        bar = context.get("bar", {})
        bar_ts = bar.get("timestamp", 0)
        # Coerce numerics (int, numpy int64, float, numeric str) so the gate
        # works regardless of how the bar's timestamp was serialised.  A
        # non-numeric/missing timestamp is treated as "unknown age" and the
        # gate accepts (it cannot prove staleness).
        try:
            ts = int(float(bar_ts))
        except (TypeError, ValueError):
            return RiskDecision(accepted=True, gate_name="stale_data")
        if ts > 0:
            age = self._now() - ts
            if age > self._max_age:
                return RiskDecision(
                    accepted=False,
                    reason=f"Bar age {age:.0f}s exceeds {self._max_age}s",
                    gate_name="stale_data",
                )
        return RiskDecision(accepted=True, gate_name="stale_data")
