"""StrategyTimeframes value object — multi-timeframe configuration.

Parsed from a strategy YAML's ``timeframes`` block. Immutable; compared by value.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, unsafe_hash=True)
class StrategyTimeframes:
    """Primary and informative timeframe declarations for a strategy.

    Attributes:
        primary: Primary execution interval (e.g. "30min").
        informative_intervals: Concrete intervals for each informative timeframe.
        informative_aliases: Mapping from alias (e.g. "h1") to interval (e.g. "1h").
            Excluded from the hash to keep the value object hashable;
            compared by equality.
    """

    primary: str | None
    informative_intervals: tuple[str, ...]
    informative_aliases: dict[str, str] = field(hash=False, compare=True)

    @property
    def is_mtf(self) -> bool:
        """True when at least one informative timeframe is declared."""
        return len(self.informative_intervals) > 0
