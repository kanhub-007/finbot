"""Strategy validator interface."""

from abc import ABC, abstractmethod

from finbot.core.domain.dto.strategy_compatibility_result import (
    StrategyCompatibilityResult,
)
from finbot.core.domain.dto.validate_strategy_request import (
    ValidateStrategyRequest,
)
from finbot.core.domain.dto.validate_strategy_result import (
    ValidateStrategyResult,
)


class StrategyValidator(ABC):
    """Validate strategy definitions and report compatibility.

    Depends on a StrategyDefinitionLoader (domain interface, not concrete).
    """

    @abstractmethod
    def validate(self, request: ValidateStrategyRequest) -> ValidateStrategyResult:
        """Parse and semantically validate a strategy definition."""

    @abstractmethod
    def compatibility(
        self, request: ValidateStrategyRequest
    ) -> StrategyCompatibilityResult:
        """Report which features are supported for each execution mode."""
