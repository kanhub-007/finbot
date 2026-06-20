"""Strategy evaluator factory interface."""

from abc import ABC, abstractmethod
from typing import Any

from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator

StrategyDefinition = Any


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
