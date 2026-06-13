"""Tests for HyperliquidMetadataProvider — standard and HIP-3 paths."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from finbot.infrastructure.adapters.hyperliquid_metadata_provider import (
    HyperliquidMetadataProvider,
)


class TestHyperliquidMetadataProviderStandard:
    """Standard perps use info.meta() — existing behavior."""

    def test_get_metadata_standard_perp(self) -> None:
        mock_info = MagicMock()
        mock_info.meta.return_value = {
            "universe": [
                {
                    "name": "BTC",
                    "szDecimals": 5,
                    "coinCdcDecimalPlaces": 0,
                    "maxLeverage": 50,
                },
                {
                    "name": "ETH",
                    "szDecimals": 4,
                    "coinCdcDecimalPlaces": 1,
                    "maxLeverage": 25,
                },
            ]
        }
        mock_info.perp_dexs.return_value = []

        with patch("hyperliquid.info.Info", return_value=mock_info):
            provider = HyperliquidMetadataProvider()
            meta = provider.get_metadata("BTC")
            assert meta is not None
            assert meta.symbol == "BTC"
            assert meta.sz_decimals == 5
            assert meta.price_tick == Decimal("1")
            assert meta.max_leverage == 50

    def test_standard_perp_caches_universe(self) -> None:
        """Second lookup doesn't hit the API."""
        mock_info = MagicMock()
        mock_info.meta.return_value = {
            "universe": [
                {
                    "name": "BTC",
                    "szDecimals": 5,
                    "coinCdcDecimalPlaces": 0,
                    "maxLeverage": 50,
                },
            ]
        }
        mock_info.perp_dexs.return_value = []

        with patch("hyperliquid.info.Info", return_value=mock_info):
            provider = HyperliquidMetadataProvider()
            _ = provider.get_metadata("BTC")
            _ = provider.get_metadata("ETH")  # cache hit, no fetch
            assert mock_info.meta.call_count == 1

    def test_unknown_standard_perp_returns_none(self) -> None:
        mock_info = MagicMock()
        mock_info.meta.return_value = {
            "universe": [
                {
                    "name": "BTC",
                    "szDecimals": 5,
                    "coinCdcDecimalPlaces": 0,
                    "maxLeverage": 50,
                },
            ]
        }
        mock_info.perp_dexs.return_value = []

        with patch("hyperliquid.info.Info", return_value=mock_info):
            provider = HyperliquidMetadataProvider()
            meta = provider.get_metadata("XYZ")
            assert meta is None

    def test_price_tick_conversion(self) -> None:
        """coinCdcDecimalPlaces → tick size."""
        mock_info = MagicMock()
        mock_info.meta.return_value = {
            "universe": [
                {
                    "name": "ETH",
                    "szDecimals": 4,
                    "coinCdcDecimalPlaces": 2,
                    "maxLeverage": 25,
                },
            ]
        }
        mock_info.perp_dexs.return_value = []

        with patch("hyperliquid.info.Info", return_value=mock_info):
            provider = HyperliquidMetadataProvider()
            meta = provider.get_metadata("ETH")
            assert meta is not None
            assert meta.price_tick == Decimal("0.01")


class TestHyperliquidMetadataProviderHip3:
    """HIP-3 perps use info.post('/info', {'type': 'metaAndAssetCtxs', 'dex': ...})."""

    def test_get_metadata_hip3_token(self) -> None:
        mock_info = MagicMock()
        # Standard universe: empty (no HIP-3 there)
        mock_info.meta.return_value = {"universe": []}
        mock_info.perp_dexs.return_value = [{"name": "flx"}, {"name": "xyz"}]
        # HIP-3 endpoint returns metaAndAssetCtxs for a specific DEX
        mock_info.post.return_value = [
            {
                "universe": [
                    {
                        "name": "flx:TSLA",
                        "szDecimals": 2,
                        "coinCdcDecimalPlaces": 2,
                        "maxLeverage": 3,
                    },
                    {
                        "name": "flx:NVDA",
                        "szDecimals": 2,
                        "coinCdcDecimalPlaces": 2,
                        "maxLeverage": 3,
                    },
                ]
            },
            [{"dayNtlVlm": "100000"}],
        ]

        with patch("hyperliquid.info.Info", return_value=mock_info):
            provider = HyperliquidMetadataProvider()
            meta = provider.get_metadata("flx:TSLA")
            assert meta is not None
            assert meta.symbol == "flx:TSLA"
            assert meta.sz_decimals == 2
            assert meta.price_tick == Decimal("0.01")
            assert meta.max_leverage == 3

    def test_hip3_caches_dex_list(self) -> None:
        """perp_dexs() is called only once within TTL."""
        mock_info = MagicMock()
        mock_info.meta.return_value = {"universe": []}
        mock_info.perp_dexs.return_value = [{"name": "flx"}]
        mock_info.post.return_value = [
            {
                "universe": [
                    {
                        "name": "flx:TSLA",
                        "szDecimals": 2,
                        "coinCdcDecimalPlaces": 2,
                        "maxLeverage": 3,
                    },
                ]
            },
            [],
        ]

        with patch("hyperliquid.info.Info", return_value=mock_info):
            provider = HyperliquidMetadataProvider()
            _ = provider.get_metadata("flx:TSLA")
            _ = provider.get_metadata("flx:NVDA")
            # perp_dexs should have been called only once
            assert mock_info.perp_dexs.call_count == 1

    def test_hip3_caches_per_dex_metadata(self) -> None:
        """Second HIP-3 call for same DEX doesn't re-fetch."""
        mock_info = MagicMock()
        mock_info.meta.return_value = {"universe": []}
        mock_info.perp_dexs.return_value = [{"name": "flx"}]
        mock_info.post.return_value = [
            {
                "universe": [
                    {
                        "name": "flx:TSLA",
                        "szDecimals": 2,
                        "coinCdcDecimalPlaces": 2,
                        "maxLeverage": 3,
                    },
                ]
            },
            [],
        ]

        with patch("hyperliquid.info.Info", return_value=mock_info):
            provider = HyperliquidMetadataProvider()
            _ = provider.get_metadata("flx:TSLA")
            _ = provider.get_metadata("flx:TSLA")  # second call, should be cached
            # post called only once for the dex lookup
            assert mock_info.post.call_count == 1

    def test_unknown_dex_returns_none(self) -> None:
        mock_info = MagicMock()
        mock_info.meta.return_value = {"universe": []}
        mock_info.perp_dexs.return_value = [{"name": "flx"}]

        with patch("hyperliquid.info.Info", return_value=mock_info):
            provider = HyperliquidMetadataProvider()
            meta = provider.get_metadata("unknown:COIN")
            assert meta is None

    def test_token_not_in_dex_returns_none(self) -> None:
        mock_info = MagicMock()
        mock_info.meta.return_value = {"universe": []}
        mock_info.perp_dexs.return_value = [{"name": "flx"}]
        mock_info.post.return_value = [
            {
                "universe": [
                    {
                        "name": "flx:TSLA",
                        "szDecimals": 2,
                        "coinCdcDecimalPlaces": 2,
                        "maxLeverage": 3,
                    },
                ]
            },
            [],
        ]

        with patch("hyperliquid.info.Info", return_value=mock_info):
            provider = HyperliquidMetadataProvider()
            meta = provider.get_metadata("flx:AAPL")  # not in flx
            assert meta is None

    def test_hip3_mixed_with_standard(self) -> None:
        """Both paths work independently."""
        mock_info = MagicMock()
        mock_info.meta.return_value = {
            "universe": [
                {
                    "name": "BTC",
                    "szDecimals": 5,
                    "coinCdcDecimalPlaces": 0,
                    "maxLeverage": 50,
                },
            ]
        }
        mock_info.perp_dexs.return_value = [{"name": "flx"}]
        mock_info.post.return_value = [
            {
                "universe": [
                    {
                        "name": "flx:TSLA",
                        "szDecimals": 2,
                        "coinCdcDecimalPlaces": 2,
                        "maxLeverage": 3,
                    },
                ]
            },
            [],
        ]

        with patch("hyperliquid.info.Info", return_value=mock_info):
            provider = HyperliquidMetadataProvider()
            btc = provider.get_metadata("BTC")
            assert btc is not None
            assert btc.symbol == "BTC"

            tsla = provider.get_metadata("flx:TSLA")
            assert tsla is not None
            assert tsla.symbol == "flx:TSLA"

    def test_dex_api_error_returns_none(self) -> None:
        """If the DEX metadata POST fails, return None rather than crash."""
        mock_info = MagicMock()
        mock_info.meta.return_value = {"universe": []}
        mock_info.perp_dexs.return_value = [{"name": "flx"}]
        mock_info.post.side_effect = Exception("API error")

        with patch("hyperliquid.info.Info", return_value=mock_info):
            provider = HyperliquidMetadataProvider()
            meta = provider.get_metadata("flx:TSLA")
            assert meta is None
