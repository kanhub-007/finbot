"""In-memory market data stream used by dry-run/testing."""

from collections.abc import Callable
from typing import Any

from finbot.core.domain.interfaces.market_data_stream import MarketDataStream


class InMemoryMarketDataStream(MarketDataStream):
    """Market data stream stub with no external network connection."""

    def subscribe_candles(
        self,
        symbol: str,
        interval: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> int:
        """Register a candle callback and return a synthetic subscription id."""
        return 1

    def stop(self) -> None:
        """Stop the in-memory stream."""
