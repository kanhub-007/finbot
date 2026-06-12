"""IndicatorSpec entity for JSON strategies."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IndicatorSpec:
    """A strategy-local indicator alias and its concrete computed column.

    Agents can reference aliases such as ``fast_sma`` in rules. Validation
    resolves those aliases to concrete indicator columns such as ``sma_20``.
    """

    name: str
    """Strategy-local alias used by conditions."""

    type: str
    """Indicator type, e.g. sma, ema, rsi, atr, or rvol."""

    concrete_name: str
    """Concrete indicator name produced by computation on its source timeframe."""

    expected_column: str = ""
    """Concrete column expected on the final backtest bar set."""

    timeframe: str = "primary"
    """Timeframe alias used to calculate this indicator."""

    sources: list[str] = field(default_factory=list)
    """Ordered fallback column names for fallback-type indicators."""

    period: int | None = None
    """Resolved period for period-based indicators."""

    source: str = "close"
    """Input source column used by the indicator layer."""

    raw_period: Any = None
    """Original period expression from JSON before parameter resolution."""

    def column_name(self) -> str:
        """Return the expected column, falling back to the concrete name."""
        return self.expected_column or self.concrete_name
