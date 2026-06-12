"""FeatureSpec entity for JSON strategy derived features."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeatureSpec:
    """A strategy-local derived feature column.

    Features are calculated by a separate indicator computation before backtesting.
    Backtesting only verifies that the resulting feature column exists.
    """

    name: str
    """Strategy-local feature alias and output column name."""

    type: str
    """Feature type, e.g. rolling_max, rolling_min, body_pct, or ohlc4."""

    source: str = "close"
    """Input column used by the feature calculator when applicable."""

    window: int | None = None
    """Optional rolling window length."""

    shift: int = 0
    """Optional positive shift applied after calculation."""

    raw_window: Any = None
    """Original window expression before parameter resolution."""

    raw_expr: Any = None
    """Original expression dict for formula-type features."""
