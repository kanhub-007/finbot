"""ManualModeGate — blocks manual orders when the run mode is misconfigured."""

from __future__ import annotations

from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.interfaces.manual_order_gate import ManualOrderGate


class ManualModeGate(ManualOrderGate):
    """Reject manual orders in live mode without explicit acknowledgment.

    Mirrors the strategy :class:`ModeGate` safety boundary: live trading must
    have ``live_trading_ack=True``. Dry-run and testnet are always allowed.
    """

    def __init__(self, mode: str, live_trading_ack: bool) -> None:
        self._mode = mode
        self._ack = live_trading_ack

    def check(self, intent: OrderIntent, context: dict[str, Any]) -> RiskDecision:
        if self._mode == "live" and not self._ack:
            return RiskDecision(
                accepted=False,
                reason="Live mode requires FINBOT_LIVE_TRADING_ACK=true",
                gate_name="manual_mode",
            )
        return RiskDecision(accepted=True, gate_name="manual_mode")
