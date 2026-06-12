"""Strategy evaluator factory interface."""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator


class StrategyEvaluatorFactory(ABC):
    """Create StrategyEvaluator instances from parsed definitions."""

    @abstractmethod
    def create(
        self,
        definition: StrategyDefinition,
        symbol: str,
        interval: str,
        strategy_hash: str,
    ) -> StrategyEvaluator:
        """Create a strategy evaluator for the given definition and context."""
