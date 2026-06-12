"""InformativeTimeframe entity for multi-timeframe strategies."""

from dataclasses import dataclass


@dataclass(frozen=True)
class InformativeTimeframe:
    """A named non-primary timeframe used for contextual indicators."""

    alias: str
    """Strategy-local timeframe alias, e.g. daily."""

    interval: str
    """Concrete bar interval, e.g. 1d."""
