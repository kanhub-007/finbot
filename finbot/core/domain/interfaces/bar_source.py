"""Bar source interface — loads historical bars for warmup."""

from abc import ABC, abstractmethod


class BarSource(ABC):
    """Abstract source for historical OHLCV bars.

    Concrete implementations load bars from CSV files, Hyperliquid
    historical candles endpoint, or other data stores.
    """

    @abstractmethod
    def load_bars(self, symbol: str, interval: str, count: int) -> list[dict]:
        """Return up to ``count`` most recent closed bars.

        Bars are returned in ascending timestamp order. Each bar dict
        must include at least: timestamp, open, high, low, close, volume.
        """
