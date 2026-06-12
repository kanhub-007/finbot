"""Order planning use case — plan an order from a strategy signal."""

from typing import Any

from finbot.core.domain.dto.order_plan_result import OrderPlanResult
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.services.order_planner import OrderPlanner


class OrderPlanningUseCase:
    """Orchestrate order planning: run signal through planner, persist intent.

    Parameters
    ----------
    planner:
        Configured :class:`OrderPlanner` with the full risk gate chain.
    """

    def __init__(self, planner: OrderPlanner) -> None:
        self._planner = planner

    def execute(
        self,
        signal: SignalDecision,
        context: dict[str, Any] | None = None,
    ) -> OrderPlanResult:
        return self._planner.plan(signal, context)
