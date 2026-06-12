"""Duplicate signal gate — rejects signals already processed."""

from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.risk_gate import RiskGate


class DuplicateSignalGate(RiskGate):
    """Reject a signal if its key has already been persisted."""

    def __init__(self, repo: BotStateRepository) -> None:
        self._repo = repo

    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        _ = context
        key = signal.signal_key
        if self._repo.has_processed_signal(key):
            return RiskDecision(
                accepted=False,
                reason=f"Duplicate signal {key}",
                gate_name="duplicate_signal",
            )
        return RiskDecision(accepted=True, gate_name="duplicate_signal")
