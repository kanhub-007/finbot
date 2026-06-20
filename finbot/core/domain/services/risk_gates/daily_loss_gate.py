"""Daily loss gate — rejects when cumulative realized loss exceeds the daily cap."""

from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.risk_gate import RiskGate


class DailyLossGate(RiskGate):
    """Reject when realized daily loss exceeds *max_loss_usd*.

    Uses realized loss only from closed trades (deterministic — no
    mark-to-market).  Exit signals (LONG_EXIT / SHORT_EXIT) always pass
    to avoid locking the bot into losing positions.
    """

    def __init__(self, max_loss_usd: Decimal = Decimal("0")) -> None:
        self._max = max_loss_usd

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        # Exit signals always bypass the daily-loss cap so the bot can
        # close positions even when over the loss limit.
        if signal.action in (SignalAction.LONG_EXIT, SignalAction.SHORT_EXIT):
            return RiskDecision(
                accepted=True,
                gate_name="daily_loss",
                reason="exits bypass daily-loss cap",
            )

        if self._max <= 0:
            return RiskDecision(accepted=True, gate_name="daily_loss")
        daily = _to_decimal(context.get("daily_loss_usd", "0"))
        if daily >= self._max:
            return RiskDecision(
                accepted=False,
                reason=f"Daily loss {daily} >= max {self._max}",
                gate_name="daily_loss",
            )
        return RiskDecision(accepted=True, gate_name="daily_loss")


def _to_decimal(value: object) -> Decimal:
    """Coerce *value* to Decimal, defaulting to 0 on failure."""
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")
