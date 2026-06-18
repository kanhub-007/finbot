"""ManualOrderGate — Chain of Responsibility step for trader-initiated orders.

Separate from :class:`RiskGate` (which operates on ``SignalDecision``) because
manual orders create ``OrderIntent`` directly with no signal. Same
:class:`RiskDecision` outcome so the chain composes uniformly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.risk_decision import RiskDecision


class ManualOrderGate(ABC):
    """One step in the manual-order risk gate chain."""

    @abstractmethod
    def check(self, intent: OrderIntent, context: dict[str, Any]) -> RiskDecision:
        """Evaluate the manual order intent and return a decision."""
