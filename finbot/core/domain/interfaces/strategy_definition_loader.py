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

    def parse_timeframes(self, content: str):
        """Parse the ``timeframes`` block from raw strategy content.

        Returns a :class:`StrategyTimeframes` when the content declares
        a ``timeframes`` block with at least a primary interval, or
        ``None`` for single-TF strategies.  The default implementation
        returns ``None`` — subclasses that understand strategy YAML
        override this.
        """
        return None

    def last_timeframes(self):  # type: ignore[empty-body]
        """Return the timeframes declared by the last-loaded strategy.

        Returns ``None`` for single-TF strategies (no ``timeframes`` block).
        Override in implementations that parse strategy YAML.
        """
        return None
