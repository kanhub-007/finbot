"""Bar loader interface — loads OHLCV bars for replay."""

from abc import ABC, abstractmethod


class BarLoader(ABC):
    """Load historical bar data for replay/backtesting."""

    @abstractmethod
    def load_bars(self, csv_text: str) -> list[dict]:
        """Parse CSV text into sorted bar dicts."""
