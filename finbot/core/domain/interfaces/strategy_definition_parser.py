"""StrategyDefinitionParser interface for JSON strategy parsing."""

from abc import ABC, abstractmethod
from typing import Any

from finbot.core.domain.entities.strategy_validation_result import (
    StrategyValidationResult,
)


class StrategyDefinitionParser(ABC):
    """Parse raw strategy JSON into canonical domain entities.

    This interface lives in the domain so both application use cases
    and infrastructure providers can depend on it without layer violations.
    """

    @abstractmethod
    def parse(
        self,
        raw_definition: str | dict,
        param_overrides: dict | None = None,
    ) -> StrategyValidationResult:
        """Parse, normalize, and validate a strategy definition.

        Args:
            raw_definition: Raw JSON string or dict from the agent.
            param_overrides: Optional runtime parameter overrides.

        Returns:
            StrategyValidationResult with canonical definition and diagnostics.
        """
        ...

    @abstractmethod
    def parse_definition(
        self,
        raw_definition: str | dict,
        param_overrides: dict | None = None,
    ) -> Any:
        """Parse and return the canonical definition entity directly.

        Returns None when parsing fails.
        """
        ...
