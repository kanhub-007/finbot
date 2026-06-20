"""Strategy definition loader interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

StrategyDefinition = Any


class StrategyDefinitionLoader(ABC):
    """Load strategy definitions from files or raw text."""

    @abstractmethod
    def load_from_text(self, content: str) -> StrategyDefinition:
        """Parse a strategy YAML/JSON string into a StrategyDefinition."""

    @abstractmethod
    def load_from_file(self, path: str) -> StrategyDefinition:
        """Parse a strategy YAML/JSON file into a StrategyDefinition."""

    @abstractmethod
    def load_content(self, path: str) -> str:
        """Read the raw strategy file content as a string.

        Separated from *load_from_file* so callers that only need the
        raw text (e.g. compatibility checks) do not pay for parsing.
        """
        ...

    def last_timeframes(self):  # type: ignore[empty-body]
        """Return the timeframes declared by the last-loaded strategy.

        Returns ``None`` for single-TF strategies (no ``timeframes`` block).
        Override in implementations that parse strategy YAML.
        """
        return None
