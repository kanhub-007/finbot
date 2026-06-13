"""Tests for HyperliquidBarSource — historical candle loading for both paths."""

from unittest.mock import MagicMock, patch

from finbot.infrastructure.strategy.hyperliquid_bar_source import (
    HyperliquidBarSource,
)


class TestHyperliquidBarSourceStandard:
    """Standard perps use info.candles_snapshot()."""

    def test_load_standard_perp_bars(self) -> None:
        mock_info = MagicMock()
        mock_info.candles_snapshot.return_value = [
            {"t": 1749000000000, "o": "50000", "h": "51000", "l": "49000",
             "c": "50500", "v": "100", "s": "BTC", "i": "1h"},
            {"t": 1749003600000, "o": "50500", "h": "52000", "l": "50500",
             "c": "51800", "v": "150", "s": "BTC", "i": "1h"},
        ]

        with (
            patch("hyperliquid.info.Info", return_value=mock_info),
            patch("time.time", return_value=1750000000.0),
        ):
            source = HyperliquidBarSource()
            bars = source.load_bars("BTC", "1h", 10)

        assert len(bars) == 2
        # Timestamps normalized ms → s
        assert bars[0]["timestamp"] == 1749000000
        assert bars[0]["close"] == 50500.0
        assert bars[1]["timestamp"] == 1749003600
        assert bars[1]["close"] == 51800.0

        mock_info.candles_snapshot.assert_called_once()
        call_args = mock_info.candles_snapshot.call_args
        assert call_args[0][0] == "BTC"
        assert call_args[0][1] == "1h"

    def test_empty_result_returns_empty_list(self) -> None:
        mock_info = MagicMock()
        mock_info.candles_snapshot.return_value = []

        with (
            patch("hyperliquid.info.Info", return_value=mock_info),
            patch("time.time", return_value=1750000000.0),
        ):
            source = HyperliquidBarSource()
            bars = source.load_bars("BTC", "1h", 10)

        assert bars == []

    def test_count_zero_returns_empty(self) -> None:
        source = HyperliquidBarSource()
        bars = source.load_bars("BTC", "1h", 0)
        assert bars == []


class TestHyperliquidBarSourceHip3:
    """HIP-3 perps use info.post('/info', {'type': 'candleSnapshot', ...})."""

    def test_load_hip3_bars(self) -> None:
        mock_info = MagicMock()
        mock_info.candles_snapshot.return_value = []
        mock_info.post.return_value = [
            {"t": 1749000000000, "o": "290.00", "h": "295.00", "l": "288.00",
             "c": "292.00", "v": "5000", "s": "xyz:AAPL", "i": "1h"},
            {"t": 1749003600000, "o": "292.00", "h": "298.00", "l": "291.00",
             "c": "296.00", "v": "6000", "s": "xyz:AAPL", "i": "1h"},
        ]

        with (
            patch("hyperliquid.info.Info", return_value=mock_info),
            patch("time.time", return_value=1750000000.0),
        ):
            source = HyperliquidBarSource()
            bars = source.load_bars("xyz:AAPL", "1h", 10)

        assert len(bars) == 2
        assert bars[0]["timestamp"] == 1749000000
        assert bars[0]["close"] == 292.0
        assert bars[1]["timestamp"] == 1749003600
        assert bars[1]["close"] == 296.0

        mock_info.post.assert_called_once()
        call_args = mock_info.post.call_args
        assert call_args[0][0] == "/info"
        req = call_args[0][1]
        assert req["type"] == "candleSnapshot"
        assert req["req"]["coin"] == "xyz:AAPL"
        assert req["req"]["interval"] == "1h"

    def test_hip3_coin_field_is_dex_colon_coin(self) -> None:
        mock_info = MagicMock()
        mock_info.post.return_value = [
            {"t": 1749000000000, "o": "400", "h": "410", "l": "400",
             "c": "408", "v": "100", "s": "flx:TSLA", "i": "1h"},
        ]

        with (
            patch("hyperliquid.info.Info", return_value=mock_info),
            patch("time.time", return_value=1750000000.0),
        ):
            source = HyperliquidBarSource()
            bars = source.load_bars("flx:TSLA", "1h", 10)

        assert len(bars) == 1
        call_args = mock_info.post.call_args
        req = call_args[0][1]
        assert req["req"]["coin"] == "flx:TSLA"

    def test_hip3_empty_response(self) -> None:
        mock_info = MagicMock()
        mock_info.post.return_value = None

        with (
            patch("hyperliquid.info.Info", return_value=mock_info),
            patch("time.time", return_value=1750000000.0),
        ):
            source = HyperliquidBarSource()
            bars = source.load_bars("flx:TSLA", "1h", 10)

        assert bars == []

    def test_hip3_api_error_returns_empty(self) -> None:
        mock_info = MagicMock()
        mock_info.post.side_effect = Exception("500 Server Error")

        with (
            patch("hyperliquid.info.Info", return_value=mock_info),
            patch("time.time", return_value=1750000000.0),
        ):
            source = HyperliquidBarSource()
            bars = source.load_bars("flx:TSLA", "1h", 10)

        assert bars == []
