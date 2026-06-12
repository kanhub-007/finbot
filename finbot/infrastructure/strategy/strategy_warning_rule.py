"""StrategyWarningRule — interface for detecting strategy issues."""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)


class StrategyWarningRule(ABC):
    """Detect a specific category of strategy issue during validation."""

    @abstractmethod
    def check(self, definition: StrategyDefinition) -> StrategyValidationError | None:
        """Return a warning if the issue is detected, or None."""
        ...
