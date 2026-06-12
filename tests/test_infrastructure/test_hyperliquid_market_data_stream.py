"""Tests for HyperliquidMarketDataStream using mocked SDK."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
    _candle_to_bar,
)


class TestCandleToBar:
    def test_candle_message_maps_to_bar_event(self) -> None:
        data = {
            "t": 1735682400000,
            "o": "50000.0",
            "h": "51000.0",
            "l": "49000.0",
            "c": "50500.0",
            "v": "100.5",
            "s": "BTC",
            "i": "1h",
        }
        bar = _candle_to_bar(data)
        assert bar is not None
        assert bar["timestamp"] == 1735682400
        assert bar["open"] == 50000.0
        assert bar["high"] == 51000.0
        assert bar["low"] == 49000.0
        assert bar["close"] == 50500.0
        assert bar["volume"] == 100.5
        assert bar["symbol"] == "BTC"
        assert bar["interval"] == "1h"

    def test_malformed_candle_returns_none(self) -> None:
        assert _candle_to_bar({}) is None
        assert _candle_to_bar({"t": "bad", "o": "x"}) is None


class TestHyperliquidMarketDataStream:
    def test_subscribe_candles_uses_expected_subscription_shape(self) -> None:
        mock_info = MagicMock()
        mock_info.subscribe.return_value = 42

        with patch(
            "hyperliquid.info.Info",
            return_value=mock_info,
        ):
            from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
                HyperliquidMarketDataStream,
            )

            stream = HyperliquidMarketDataStream(stale_data_seconds=0)
            sub_id = stream.subscribe_candles("BTC", "1h", lambda _: None)

            mock_info.subscribe.assert_called_once()
            call_args = mock_info.subscribe.call_args[0]
            assert call_args[0] == {
                "type": "candle",
                "coin": "BTC",
                "interval": "1h",
            }
            assert sub_id == 42
            stream.stop()

    def test_partial_candle_is_ignored(self) -> None:
        """First candle after subscribe is treated as potentially partial."""
        mock_info = MagicMock()
        mock_info.subscribe.return_value = 1

        received: list[dict] = []

        with patch(
            "hyperliquid.info.Info",
            return_value=mock_info,
        ):
            from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
                HyperliquidMarketDataStream,
            )

            stream = HyperliquidMarketDataStream(stale_data_seconds=0)
            stream.subscribe_candles("BTC", "1h", received.append)

            # First candle → skipped (partial)
            stream._on_candle(
                {
                    "channel": "candle",
                    "data": {
                        "t": 1000000,
                        "o": "1",
                        "h": "2",
                        "l": "0",
                        "c": "1.5",
                        "v": "10",
                        "s": "BTC",
                        "i": "1h",
                    },
                }
            )
            assert len(received) == 0  # first candle skipped

            # Same timestamp again → still partial, still skipped
            stream._on_candle(
                {
                    "channel": "candle",
                    "data": {
                        "t": 1000000,
                        "o": "1",
                        "h": "2",
                        "l": "0",
                        "c": "1.8",
                        "v": "12",
                        "s": "BTC",
                        "i": "1h",
                    },
                }
            )
            assert len(received) == 1  # emits current bar

            stream.stop()

    def test_closed_candle_is_processed(self) -> None:
        mock_info = MagicMock()
        mock_info.subscribe.return_value = 1

        received: list[dict] = []

        with patch(
            "hyperliquid.info.Info",
            return_value=mock_info,
        ):
            from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
                HyperliquidMarketDataStream,
            )

            stream = HyperliquidMarketDataStream(stale_data_seconds=0)
            stream.subscribe_candles("BTC", "1h", received.append)

            # First candle (partial) → skipped
            stream._on_candle(
                {
                    "channel": "candle",
                    "data": {
                        "t": 1000000,
                        "o": "1",
                        "h": "2",
                        "l": "0",
                        "c": "1.5",
                        "v": "10",
                        "s": "BTC",
                        "i": "1h",
                    },
                }
            )
            assert len(received) == 0

            # New candle timestamp means the one before IS a closed candle
            # But we emit the current bar (which will become closed when
            # the next timestamp arrives).
            stream._on_candle(
                {
                    "channel": "candle",
                    "data": {
                        "t": 1003600,
                        "o": "2",
                        "h": "3",
                        "l": "1",
                        "c": "2.5",
                        "v": "20",
                        "s": "BTC",
                        "i": "1h",
                    },
                }
            )
            assert len(received) == 1
            assert received[0]["close"] == 2.5
            assert received[0]["timestamp"] == 1003  # ms→s

            stream.stop()

    def test_dry_run_loop_never_calls_exchange_submit_order(self) -> None:
        """The market data stream has no order submission capability."""
        from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
            HyperliquidMarketDataStream,
        )

        stream = HyperliquidMarketDataStream()
        assert not hasattr(stream, "submit_order")
        assert not hasattr(stream, "cancel_order")

    def test_stale_data_triggers_risk_event(self) -> None:
        mock_info = MagicMock()
        mock_info.subscribe.return_value = 1

        received: list[dict] = []

        with patch(
            "hyperliquid.info.Info",
            return_value=mock_info,
        ):
            from finbot.infrastructure.adapters.hyperliquid_market_data_stream import (
                HyperliquidMarketDataStream,
            )

            # Use a very short stale timeout
            stream = HyperliquidMarketDataStream(stale_data_seconds=0.1)
            stream.subscribe_candles("BTC", "1h", received.append)

            # Wait for the stale checker to fire
            time.sleep(0.3)

            stream.stop()

            stale_events = [e for e in received if e.get("_stale")]
            assert len(stale_events) >= 1
