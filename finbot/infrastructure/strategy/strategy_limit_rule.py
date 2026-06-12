"""StrategyLimitRule — interface for enforcing SDK limits."""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)


class StrategyLimitRule(ABC):
    """Enforce a specific limit on strategy definitions."""

    @abstractmethod
    def check(
        self,
        definition: StrategyDefinition,
        params: dict,
        indicators: list,
        features: list,
    ) -> StrategyValidationError | None:
        """Return an error if the limit is exceeded, or None."""
        ...
