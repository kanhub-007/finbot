"""Historical CSV bar source — wraps CsvBarLoader as a BarSource."""

from finbot.core.domain.interfaces.bar_source import BarSource
from finbot.infrastructure.strategy.csv_bar_loader import CsvBarLoader


class HistCsvBarSource(BarSource):
    """Load closed bars from CSV files for warmup.

    Wraps the existing CsvBarLoader so it satisfies the BarSource
    interface expected by the warmup orchestration layer.

    Parameters
    ----------
    csv_text:
        Raw CSV content to parse. All bars are treated as closed.
    """

    def __init__(self, csv_text: str = "") -> None:
        self._loader = CsvBarLoader()
        self._csv_text = csv_text
        self._cached_bars: list[dict] | None = None

    @property
    def csv_text(self) -> str:
        return self._csv_text

    @csv_text.setter
    def csv_text(self, value: str) -> None:
        self._csv_text = value
        self._cached_bars = None

    def load_bars(self, symbol: str, interval: str, count: int) -> list[dict]:
        _ = symbol, interval
        if self._cached_bars is None:
            self._cached_bars = self._loader.load_bars(self._csv_text)
        bars = self._cached_bars
        if count and count < len(bars):
            return bars[-count:]
        return list(bars)
