"""Order planner interface — domain abstraction for signal-to-intent conversion.

Concrete implementations run risk gates and produce :class:`OrderPlanResult`.
"""

from abc import ABC, abstractmethod
from typing import Any

from finbot.core.domain.dto.order_plan_result import OrderPlanResult
from finbot.core.domain.entities.signal_decision import SignalDecision


class OrderPlanner(ABC):
    """Plan an order from a strategy signal, including risk evaluation."""

    @abstractmethod
    def plan(
        self,
        signal: SignalDecision,
        context: dict[str, Any] | None = None,
    ) -> OrderPlanResult:
        """Evaluate the signal through risk gates and return a plan.

        Args:
            signal: Strategy signal to evaluate.
            context: Extra data available to risk gates (bar, position, etc.).

        Returns:
            An ``OrderPlanResult`` indicating acceptance and optionally
            an ``OrderIntent``.
        """
