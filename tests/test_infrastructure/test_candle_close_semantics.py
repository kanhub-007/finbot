"""Tests for closed-candle semantics in HyperliquidMarketDataStream."""

from unittest.mock import MagicMock, patch

from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
    HyperliquidMarketDataStream,
)


class TestCandleCloseSemantics:
    def _make_candle(self, ts_ms: int, close: float) -> dict:
        return {
            "channel": "candle",
            "data": {
                "t": ts_ms,
                "o": str(close - 1),
                "h": str(close + 1),
                "l": str(close - 2),
                "c": str(close),
                "v": "100",
                "s": "BTC",
                "i": "1h",
            },
        }

    def test_partial_candle_update_is_not_processed(self) -> None:
        """Updates to the same (forming) candle are silently stored, not emitted."""
        mock_info = MagicMock()
        mock_info.subscribe.return_value = 1
        emitted: list[dict] = []

        with patch("hyperliquid.info.Info", return_value=mock_info):
            stream = HyperliquidMarketDataStream(stale_data_seconds=0)
            stream.subscribe_candles("BTC", "1h", emitted.append)

            # First candle (forming) — captured, not emitted
            stream._on_candle(self._make_candle(1000000, 50000.0))
            assert len(emitted) == 0

            # Same candle update (still forming) — still not emitted
            stream._on_candle(self._make_candle(1000000, 50100.0))
            assert len(emitted) == 0

            stream.stop()

    def test_candle_is_processed_when_next_candle_starts(self) -> None:
        """New candle timestamp → previous is emitted as closed."""
        mock_info = MagicMock()
        mock_info.subscribe.return_value = 1
        emitted: list[dict] = []

        with patch("hyperliquid.info.Info", return_value=mock_info):
            stream = HyperliquidMarketDataStream(stale_data_seconds=0)
            stream.subscribe_candles("BTC", "1h", emitted.append)

            # Candle A (forming)
            stream._on_candle(self._make_candle(1000000, 50000.0))
            assert len(emitted) == 0

            # Candle B starts → candle A is now closed
            stream._on_candle(self._make_candle(1003600, 51000.0))
            assert len(emitted) == 1
            assert emitted[0]["close"] == 50000.0
            assert emitted[0]["_closed"] is True
            assert emitted[0]["timestamp"] == 1000  # ms→s

            stream.stop()

    def test_same_closed_candle_not_emitted_twice(self) -> None:
        """A candle that was already emitted as closed is not emitted again."""
        mock_info = MagicMock()
        mock_info.subscribe.return_value = 1
        emitted: list[dict] = []

        with patch("hyperliquid.info.Info", return_value=mock_info):
            stream = HyperliquidMarketDataStream(stale_data_seconds=0)
            stream.subscribe_candles("BTC", "1h", emitted.append)

            stream._on_candle(self._make_candle(1000000, 50000.0))
            stream._on_candle(self._make_candle(1003600, 51000.0))
            assert len(emitted) == 1  # candle A emitted

            # Duplicate update for the same closed candle should be ignored
            stream._on_candle(self._make_candle(1003600, 51200.0))
            assert len(emitted) == 1  # still just 1

            stream.stop()

    def test_out_of_order_candle_does_not_trigger_duplicate_signal(self) -> None:
        """An older timestamp arriving after a newer one is silently ignored."""
        mock_info = MagicMock()
        mock_info.subscribe.return_value = 1
        emitted: list[dict] = []

        with patch("hyperliquid.info.Info", return_value=mock_info):
            stream = HyperliquidMarketDataStream(stale_data_seconds=0)
            stream.subscribe_candles("BTC", "1h", emitted.append)

            stream._on_candle(self._make_candle(1000000, 50000.0))
            stream._on_candle(self._make_candle(1003600, 51000.0))
            assert len(emitted) == 1

            # Out-of-order: older timestamp after newer was already seen
            stream._on_candle(self._make_candle(1000000, 49000.0))
            assert len(emitted) == 1  # ignored

            stream.stop()
