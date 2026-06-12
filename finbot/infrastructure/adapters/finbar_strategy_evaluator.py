"""Finbar-backed strategy evaluator placeholder."""

from typing import Any

from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator


class FinbarStrategyEvaluator(StrategyEvaluator):
    """Evaluates Finbar YAML/JSON strategies through a narrow adapter.

    The concrete implementation will import Finbar here, not in domain or
    application code.
    """

    def __init__(self, strategy_path: str):
        self._strategy_path = strategy_path

    def evaluate(
        self,
        enriched_bar: dict[str, Any],
        position: PositionSnapshot,
    ) -> SignalDecision:
        """Evaluate one enriched closed bar with the configured strategy."""
        return SignalDecision(action=SignalAction.HOLD)
