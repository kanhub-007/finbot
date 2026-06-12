"""Hyperliquid metadata provider — reads symbol constraints from the SDK."""

from __future__ import annotations

from decimal import Decimal

from finbot.core.domain.entities.market_metadata import MarketMetadata
from finbot.core.domain.interfaces.market_metadata_provider import (
    MarketMetadataProvider,
)


class HyperliquidMetadataProvider(MarketMetadataProvider):
    """Fetches per-symbol order constraints from Hyperliquid ``Info``.

    The full universe is fetched once and cached.  Individual symbol
    lookups never trigger additional HTTP requests.

    Parameters
    ----------
    base_url:
        Hyperliquid API base URL.
    """

    def __init__(self, base_url: str = "https://api.hyperliquid.xyz") -> None:
        self._base_url = base_url
        self._cache: dict[str, MarketMetadata] = {}
        self._fetched = False

    def get_metadata(self, symbol: str) -> MarketMetadata | None:
        key = symbol.upper()
        if key in self._cache:
            return self._cache[key]
        if self._fetched:
            return None

        from hyperliquid.info import Info

        info = Info(self._base_url, skip_ws=True)
        meta_list = info.meta()
        self._fetched = True

        universe = meta_list.get("universe", [])
        for asset in universe:
            name = asset.get("name", "")
            md = MarketMetadata(
                symbol=name,
                sz_decimals=asset.get("szDecimals", 0),
                price_tick=_tick_to_decimal(asset.get("coinCdcDecimalPlaces", 0)),
                max_leverage=asset.get("maxLeverage", 0),
            )
            self._cache[name.upper()] = md

        return self._cache.get(key)


def _tick_to_decimal(places: int) -> Decimal:
    """Convert decimal places to tick size (e.g. 0 → 1, 1 → 0.1)."""
    return Decimal("1").scaleb(-places) if places >= 0 else Decimal("1")
