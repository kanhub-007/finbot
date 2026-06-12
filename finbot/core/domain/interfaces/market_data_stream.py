"""Market data stream interface."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class MarketDataStream(ABC):
    """Abstracts realtime market data subscriptions."""

    @abstractmethod
    def subscribe_candles(
        self,
        symbol: str,
        interval: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> int:
        """Subscribe to candle updates and return a subscription id."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the stream and release network resources."""
