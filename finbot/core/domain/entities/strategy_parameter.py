"""StrategyParameter entity for JSON strategies."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyParameter:
    """A typed runtime parameter for a JSON strategy.

    Parameters allow agents to author reusable strategies whose concrete
    indicator periods or thresholds are resolved before validation/backtesting.
    """

    name: str
    """Unique parameter name within one strategy definition."""

    type: str
    """Parameter type: int, float, bool, or string."""

    default: Any
    """Default value used when no runtime override is supplied."""

    minimum: float | None = None
    """Optional lower bound for numeric parameters."""

    maximum: float | None = None
    """Optional upper bound for numeric parameters."""

    description: str = ""
    """Human-readable parameter description."""
