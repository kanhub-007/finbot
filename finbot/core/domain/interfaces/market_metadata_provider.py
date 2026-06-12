"""Market metadata provider interface."""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.market_metadata import MarketMetadata


class MarketMetadataProvider(ABC):
    """Provides exchange-specific order constraints per symbol."""

    @abstractmethod
    def get_metadata(self, symbol: str) -> MarketMetadata | None:
        """Return metadata for *symbol*, or None if unknown."""
