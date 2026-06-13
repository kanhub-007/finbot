"""Hyperliquid bar source — loads historical candles for warmup.

Routes standard perps through ``info.candles_snapshot()`` and HIP-3
perps (``dex:COIN`` format) through a custom ``candleSnapshot`` POST.

Candle timestamps are normalized from milliseconds to seconds.
"""

from __future__ import annotations

import time
from typing import Any

from finbot.core.domain.interfaces.bar_source import BarSource

_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


class HyperliquidBarSource(BarSource):
    """Loads historical OHLCV bars from Hyperliquid.

    Parameters
    ----------
    base_url:
        Hyperliquid API base URL.  Defaults to mainnet.
    """

    def __init__(
        self,
        base_url: str = "https://api.hyperliquid.xyz",
    ) -> None:
        self._base_url = base_url

    # -- BarSource --------------------------------------------------------

    def load_bars(
        self,
        symbol: str,
        interval: str,
        count: int,
    ) -> list[dict]:
        if count <= 0:
            return []

        interval_ms = _INTERVAL_MS.get(interval, 3_600_000)
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - (count * interval_ms)
        end_ms = now_ms

        if ":" in symbol:
            raw_candles = self._fetch_hip3_candles(symbol, interval, start_ms, end_ms)
        else:
            raw_candles = self._fetch_standard_candles(
                symbol, interval, start_ms, end_ms
            )

        return _normalize_candles(raw_candles)

    # -- internal ---------------------------------------------------------

    def _fetch_standard_candles(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> list[dict[str, Any]]:
        from hyperliquid.info import Info

        info = Info(self._base_url, skip_ws=True)
        return info.candles_snapshot(symbol, interval, start_ms, end_ms) or []

    def _fetch_hip3_candles(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> list[dict[str, Any]]:
        from hyperliquid.info import Info

        info = Info(self._base_url, skip_ws=True)
        try:
            result = info.post(
                "/info",
                {
                    "type": "candleSnapshot",
                    "req": {
                        "coin": symbol,
                        "interval": interval,
                        "startTime": start_ms,
                        "endTime": end_ms,
                    },
                },
            )
        except Exception:
            return []
        return result if isinstance(result, list) else []


def _normalize_candles(
    raw: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert Hyperliquid candle dicts to normalized bar dicts.

    Timestamps are converted from milliseconds to seconds.
    String OHLCV values are converted to floats.
    """
    bars: list[dict[str, Any]] = []
    for c in raw:
        ts = c.get("t", 0)
        if ts == 0:
            continue
        bars.append(
            {
                "timestamp": int(ts) // 1000,  # ms → s (matches websocket)
                "open": float(c.get("o", 0)),
                "high": float(c.get("h", 0)),
                "low": float(c.get("l", 0)),
                "close": float(c.get("c", 0)),
                "volume": float(c.get("v", 0)),
                "symbol": str(c.get("s", "")),
                "interval": str(c.get("i", "")),
            }
        )
    return bars
