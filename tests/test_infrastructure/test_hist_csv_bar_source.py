"""Tests for HistCsvBarSource."""

from finbot.infrastructure.strategy.hist_csv_bar_source import HistCsvBarSource


class TestHistCsvBarSource:
    def test_loads_bars_from_csv(self) -> None:
        csv = (
            "timestamp,open,high,low,close,volume\n"
            "2025-01-01T09:00,100,102,99,101,1000\n"
            "2025-01-01T10:00,101,103,100,102,1100\n"
        )
        source = HistCsvBarSource(csv)
        bars = source.load_bars("BTC", "1h", 10)
        assert len(bars) == 2
        assert bars[0]["close"] == 101.0
        assert bars[1]["close"] == 102.0

    def test_respects_count_limit(self) -> None:
        csv = (
            "timestamp,open,high,low,close,volume\n"
            "2025-01-01T09:00,100,102,99,101,1000\n"
            "2025-01-01T10:00,101,103,100,102,1100\n"
            "2025-01-01T11:00,102,104,101,103,1200\n"
        )
        source = HistCsvBarSource(csv)
        bars = source.load_bars("BTC", "1h", 2)
        assert len(bars) == 2
        # Should return the most recent bars
        assert bars[0]["timestamp"] == "2025-01-01T10:00"
        assert bars[1]["timestamp"] == "2025-01-01T11:00"

    def test_count_zero_returns_all(self) -> None:
        csv = (
            "timestamp,open,high,low,close,volume\n"
            "2025-01-01T09:00,100,102,99,101,1000\n"
        )
        source = HistCsvBarSource(csv)
        bars = source.load_bars("BTC", "1h", 0)
        assert len(bars) == 1
