"""ManualMaxPositionGate — rejects manual orders exceeding the notional cap."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.runtime_bot_config import RuntimeBotConfig
from finbot.core.domain.interfaces.manual_order_gate import ManualOrderGate


class ManualMaxPositionGate(ManualOrderGate):
    """Reject manual entries whose notional exceeds the config limit.

    Reads the live limit from :class:`RuntimeBotConfig` so ``/config`` changes
    take effect immediately. ``max_position=0`` disables the gate.
    """

    def __init__(self, config: RuntimeBotConfig) -> None:
        self._config = config

    def check(self, intent: OrderIntent, context: dict[str, Any]) -> RiskDecision:
        limit = self._config.max_position_usd
        if limit <= 0:
            return RiskDecision(accepted=True, gate_name="manual_max_position")

        price = context.get("price")
        if price is None:
            # Without a price we cannot compute notional — fail open to avoid
            # blocking closes, but entries should always pass a price.
            return RiskDecision(accepted=True, gate_name="manual_max_position")

        notional = Decimal(str(intent.size)) * Decimal(str(price))
        if notional > limit:
            return RiskDecision(
                accepted=False,
                reason=f"Notional {notional} > max {limit}",
                gate_name="manual_max_position",
            )
        return RiskDecision(accepted=True, gate_name="manual_max_position")
