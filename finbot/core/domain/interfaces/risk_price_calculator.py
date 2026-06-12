"""RiskPriceCalculator interface for strategy signal risk levels."""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.risk_spec import RiskSpec


class RiskPriceCalculator(ABC):
    """Calculate stop-loss and take-profit prices for entry signals."""

    @abstractmethod
    def calculate(
        self, risk: RiskSpec | None, bar: dict, side: str
    ) -> tuple[float, float]:
        """Return stop and target prices for an entry signal."""
