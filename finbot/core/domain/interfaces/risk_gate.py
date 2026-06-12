"""Risk gate interface — Chain of Responsibility step."""

from abc import ABC, abstractmethod
from typing import Any

from finbot.core.domain.entities.risk_decision import RiskDecision
from finbot.core.domain.entities.signal_decision import SignalDecision


class RiskGate(ABC):
    """One step in the risk gate chain.

    Each gate evaluates a signal against a specific risk rule
    (mode, duplicate, stale data, position size, etc.) and
    returns a :class:`RiskDecision`.
    """

    @abstractmethod
    def check(self, signal: SignalDecision, context: dict[str, Any]) -> RiskDecision:
        """Evaluate the signal and return a decision."""
