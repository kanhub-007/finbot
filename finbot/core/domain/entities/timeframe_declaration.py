"""TimeframeDeclaration entity for multi-timeframe strategies."""

from dataclasses import dataclass, field

from finbot.core.domain.entities.informative_timeframe import InformativeTimeframe


@dataclass(frozen=True)
class TimeframeDeclaration:
    """Primary and informative timeframe declarations for a strategy."""

    primary: str = ""
    """Primary execution timeframe, e.g. 1h or 1d."""

    informative: list[InformativeTimeframe] = field(default_factory=list)
    """Named informative timeframes used for contextual columns."""

    def interval_for(self, alias: str) -> str | None:
        """Return the concrete interval for a timeframe alias."""
        if alias == "primary":
            return self.primary
        for item in self.informative:
            if item.alias == alias:
                return item.interval
        return None

    def has_informative(self) -> bool:
        """Return whether at least one informative timeframe is declared."""
        return bool(self.informative)
