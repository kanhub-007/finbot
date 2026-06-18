"""Hyperliquid metadata provider — reads symbol constraints from the SDK.

Supports standard perpetuals (BTC, ETH) and HIP-3 vault perpetuals
(flx:TSLA, xyz:AAPL).  HIP-3 metadata is fetched via the perp_dexs
endpoint and cached per DEX for 5 minutes.
"""

from __future__ import annotations

import time
from decimal import Decimal

from finbot.core.domain.entities.market_metadata import MarketMetadata
from finbot.core.domain.interfaces.market_metadata_provider import (
    MarketMetadataProvider,
)


class HyperliquidMetadataProvider(MarketMetadataProvider):
    """Fetches per-symbol order constraints from Hyperliquid ``Info``.

    *Standard perps* — universe fetched once from ``info.meta()`` and
    cached permanently.

    *HIP-3 perps* — ``info.perp_dexs()`` list cached for 5 min.
    Per-DEX ``metaAndAssetCtxs`` fetched lazily and cached
    permanently once loaded.

    Parameters
    ----------
    base_url:
        Hyperliquid API base URL.
    perp_dexs_ttl:
        Seconds to cache the DEX provider list.  Default 300 (5 min).
    """

    _PERP_DEXS_TTL: float = 300.0  # class-level default

    def list_symbols(self) -> list[str]:
        """Return all available perp symbols (standard + HIP-3).

        Fetches from Hyperliquid on first call, caches permanently.
        """
        self._ensure_standard_fetched()
        symbols = list(self._cache.keys())

        # Add HIP-3 symbols
        for dex in self._get_perp_dexs():
            self._ensure_dex_fetched(dex)
            dex_cache = self._dex_meta_cache.get(dex, {})
            symbols.extend(dex_cache.keys())

        return sorted(symbols)

    def _ensure_standard_fetched(self) -> None:
        """Fetch standard perp universe if not already cached."""
        if self._fetched:
            return
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
                price_tick=_tick_to_decimal(
                    asset.get("coinCdcDecimalPlaces", 0)
                ),
                max_leverage=asset.get("maxLeverage", 0),
            )
            self._cache[name.upper()] = md

    def _ensure_dex_fetched(self, dex: str) -> None:
        """Fetch HIP-3 DEX metadata if not already cached."""
        if self._dex_fetched.get(dex):
            return
        from hyperliquid.info import Info

        try:
            info = Info(self._base_url, skip_ws=True)
            result = info.post(
                "/info",
                {"type": "metaAndAssetCtxs", "dex": dex},
            )
        except Exception:
            self._dex_fetched[dex] = True
            return

        if not result or len(result) < 1:
            self._dex_fetched[dex] = True
            return

        meta = result[0]
        universe = meta.get("universe", []) if isinstance(meta, dict) else []

        per_dex: dict[str, MarketMetadata] = {}
        for asset in universe:
            name = asset.get("name", "")
            md = MarketMetadata(
                symbol=name,
                sz_decimals=asset.get("szDecimals", 0),
                price_tick=_tick_to_decimal(
                    asset.get("coinCdcDecimalPlaces", 0)
                ),
                max_leverage=asset.get("maxLeverage", 0),
            )
            per_dex[name] = md

        self._dex_meta_cache[dex] = per_dex
        self._dex_fetched[dex] = True

    def __init__(
        self,
        base_url: str = "https://api.hyperliquid.xyz",
        perp_dexs_ttl: float = 300.0,
    ) -> None:
        self._base_url = base_url
        self._perp_dexs_ttl = perp_dexs_ttl
        # Standard perp cache
        self._cache: dict[str, MarketMetadata] = {}
        self._fetched = False
        # HIP-3 caches
        self._perp_dexs_cache: list[str] | None = None
        self._perp_dexs_cache_time: float = 0.0
        # dex name → {api_symbol: MarketMetadata}
        self._dex_meta_cache: dict[str, dict[str, MarketMetadata]] = {}
        self._dex_fetched: dict[str, bool] = {}

    def get_metadata(self, symbol: str) -> MarketMetadata | None:
        # ── HIP-3 path ──
        if ":" in symbol:
            return self._get_hip3_metadata(symbol)

        # ── Standard perp path ──
        self._ensure_standard_fetched()
        return self._cache.get(symbol.upper())

    # ── HIP-3 internals ──────────────────────────────────────────────

    def _get_hip3_metadata(self, symbol: str) -> MarketMetadata | None:
        """Fetch metadata for a HIP-3 ``dex:COIN`` symbol."""
        parts = symbol.split(":")
        if len(parts) != 2:
            return None
        dex = parts[0].lower()
        coin = parts[1].upper()
        api_symbol = f"{dex}:{coin}"

        # Check per-dex cache
        dex_cache = self._dex_meta_cache.get(dex)
        if dex_cache is not None:
            return dex_cache.get(api_symbol)

        if self._dex_fetched.get(dex):
            return None

        self._ensure_dex_fetched(dex)
        return self._dex_meta_cache.get(dex, {}).get(api_symbol)

    def _get_perp_dexs(self) -> list[str]:
        """Return cached DEX provider list, refreshing if expired."""
        now = time.time()
        if (
            self._perp_dexs_cache is not None
            and (now - self._perp_dexs_cache_time) < self._perp_dexs_ttl
        ):
            return self._perp_dexs_cache

        from hyperliquid.info import Info

        temp_info = Info(self._base_url, skip_ws=True)
        perps = temp_info.perp_dexs()
        self._perp_dexs_cache = [d["name"] for d in perps if d and d.get("name")]
        self._perp_dexs_cache_time = now
        return self._perp_dexs_cache


def _tick_to_decimal(places: int) -> Decimal:
    """Convert decimal places to tick size (e.g. 0 → 1, 1 → 0.1)."""
    return Decimal("1").scaleb(-places) if places >= 0 else Decimal("1")
