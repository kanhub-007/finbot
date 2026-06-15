"""Strategy definition loader interface."""

from abc import ABC, abstractmethod

from finbar_strategy_runtime.domain.entities.strategy_definition import (
    StrategyDefinition,
)


class StrategyDefinitionLoader(ABC):
    """Load strategy definitions from files or raw text."""

    @abstractmethod
    def load_from_text(self, content: str) -> StrategyDefinition:
        """Parse a strategy YAML/JSON string into a StrategyDefinition."""

    @abstractmethod
    def load_from_file(self, path: str) -> StrategyDefinition:
        """Parse a strategy YAML/JSON file into a StrategyDefinition."""
