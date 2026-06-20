"""Hyperliquid market data stream — realtime candles via WebSocket.

Wraps the Hyperliquid SDK ``Info`` class to subscribe to candle
updates and convert them into normalized bar dicts for the bot
event loop.

All network I/O is delegated to the SDK.  This adapter is
responsible for:
* Subscribing / unsubscribing
* Converting raw candle messages → bar dicts
* Detecting closed candles (ignore partials)
* Enforcing a stale-data timeout
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from finbot.core.domain.interfaces.market_data_stream import MarketDataStream

if TYPE_CHECKING:
    from hyperliquid.info import Info

logger = logging.getLogger(__name__)


class HyperliquidMarketDataStream(MarketDataStream):
    """Live Hyperliquid candle subscription via WebSocket.

    Supports both standard perps (BTC, ETH) and HIP-3 vault perps
    (flx:TSLA, xyz:AAPL).  HIP-3 symbols are handled by loading the
    DEX metadata into the SDK ``Info`` object and registering the full
    ``dex:COIN`` symbol in ``name_to_coin`` so the remap is an identity
    passthrough.

    Parameters
    ----------
    base_url:
        Hyperliquid API base URL.  Defaults to mainnet.
    stale_data_seconds:
        Seconds without a candle update before the stream is
        considered stale.  0 = disabled.
    """

    def __init__(
        self,
        base_url: str = "https://api.hyperliquid.xyz",
        stale_data_seconds: float = 120,
    ) -> None:
        self._base_url = base_url
        self._stale_seconds = stale_data_seconds
        self._info: Info | None = None
        self._sub_id: int | None = None
        self._symbol: str = ""
        self._interval: str = ""
        self._is_hip3: bool = False
        # Candle close tracking
        self._pending_bar: dict[str, Any] | None = None
        self._current_candle_ts_ms: int = 0
        self._last_emitted_ts_ms: int = 0
        self._last_update_at: float = 0.0
        self._user_callback: Callable[[dict[str, Any]], None] | None = None
        self._stop_event = threading.Event()
        self._stale_checker: threading.Thread | None = None

    # -- MarketDataStream ---------------------------------------------------

    def subscribe_candles(
        self,
        symbol: str,
        interval: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> int:
        if self._info is not None:
            raise RuntimeError("Already subscribed — call stop() first")

        self._symbol = symbol
        self._interval = interval
        self._user_callback = callback
        self._last_update_at = time.monotonic()
        # Reset candle close tracking for the new connection.
        self._pending_bar = None
        self._current_candle_ts_ms = 0
        self._last_emitted_ts_ms = 0

        self._is_hip3 = ":" in symbol

        from hyperliquid.info import Info

        if self._is_hip3:
            dex = symbol.split(":")[0]
            # Info fetches dex metadata so candle data includes the correct
            # asset index.  The coin remap inside subscribe() uses
            # name_to_coin which only maps bare coin names (e.g. PALLADIUM),
            # not dex:COIN.  Register the full symbol so the remap is an
            # identity passthrough and the websocket receives flx:PALLADIUM.
            self._info = Info(self._base_url, skip_ws=False, perp_dexs=[dex])
            self._info.name_to_coin[symbol] = symbol
            logger.info(
                "HIP-3 symbol %s — subscribed via websocket (dex=%s)", symbol, dex
            )
        else:
            self._info = Info(self._base_url, skip_ws=False)

        self._sub_id = self._info.subscribe(
            {"type": "candle", "coin": symbol, "interval": interval},
            self._on_candle,
        )
        self._start_stale_checker()
        return self._sub_id

    def stop(self) -> None:
        self._stop_event.set()
        if self._sub_id is not None and self._info is not None:
            try:
                self._info.unsubscribe(
                    {
                        "type": "candle",
                        "coin": self._symbol,
                        "interval": self._interval,
                    },
                    self._sub_id,
                )
            except Exception:
                pass
        if self._info is not None:
            try:
                self._info.ws_manager.stop()
            except Exception:
                pass
        if self._stale_checker is not None:
            self._stale_checker.join(timeout=2)
            self._stale_checker = None
        self._info = None
        self._sub_id = None
        self._user_callback = None
        self._symbol = ""
        self._interval = ""
        self._is_hip3 = False

    # -- internal -----------------------------------------------------------

    def _on_candle(self, ws_msg: dict[str, Any]) -> None:
        self._last_update_at = time.monotonic()

        if ws_msg.get("channel") != "candle":
            return
        data = ws_msg.get("data", {})
        bar = _candle_to_bar(data)
        if bar is None:
            return

        ts_ms: int = data.get("t", 0)
        cb = self._user_callback
        if cb is None:
            return

        # First candle after subscribe — capture it, don't emit yet.
        # Unless the candle's close time (T) is already in the past
        # (low-volume HIP-3 tokens where we joined after close).
        if self._current_candle_ts_ms == 0:
            self._pending_bar = bar
            self._current_candle_ts_ms = ts_ms
            t_close = data.get("T", 0)
            if t_close and int(time.time() * 1000) > t_close:
                closed = dict(bar)
                closed["_closed"] = True
                cb(closed)
                self._last_emitted_ts_ms = ts_ms
            return

        # Same candle still forming — update pending bar silently.
        if ts_ms == self._current_candle_ts_ms:
            self._pending_bar = bar
            return

        # New candle started → previous is now closed.
        if ts_ms > self._current_candle_ts_ms:
            # Emit the closed bar if it hasn't been emitted already.
            if (
                self._pending_bar is not None
                and self._current_candle_ts_ms > self._last_emitted_ts_ms
            ):
                closed = dict(self._pending_bar)
                closed["_closed"] = True
                cb(closed)
                self._last_emitted_ts_ms = self._current_candle_ts_ms
            # Start tracking the new candle.
            self._pending_bar = bar
            self._current_candle_ts_ms = ts_ms
            return

        # ts_ms < current — out-of-order; ignore.

    # -- stale data checker ------------------------------------------------

    def _start_stale_checker(self) -> None:
        if self._stale_seconds <= 0:
            return

        def _check() -> None:
            while not self._stop_event.wait(self._stale_seconds):
                if self._user_callback is None:
                    return
                elapsed = time.monotonic() - self._last_update_at
                if elapsed > self._stale_seconds:
                    self._user_callback(
                        {
                            "_stale": True,
                            "elapsed_seconds": elapsed,
                        }
                    )

        self._stale_checker = threading.Thread(target=_check, daemon=True)
        self._stale_checker.start()


def _candle_to_bar(data: dict[str, Any]) -> dict[str, Any] | None:
    """Map a Hyperliquid candle payload to a bar dict.

    Returns None when the payload is malformed or empty.
    """
    if not data:
        return None
    try:
        ts = data.get("t")
        if ts is None or ts == 0:
            return None
        return {
            "timestamp": int(ts) // 1000,  # ms → s
            "open": float(data.get("o", 0)),
            "high": float(data.get("h", 0)),
            "low": float(data.get("l", 0)),
            "close": float(data.get("c", 0)),
            "volume": float(data.get("v", 0)),
            "symbol": str(data.get("s", "")),
            "interval": str(data.get("i", "")),
        }
    except (TypeError, ValueError):
        return None
