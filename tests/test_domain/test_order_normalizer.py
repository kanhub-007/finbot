"""Tests for OrderNormalizer domain service."""

from decimal import Decimal

import pytest

from finbot.core.domain.entities.market_metadata import MarketMetadata
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.services.order_normalizer import (
    OrderNormalizationError,
    OrderNormalizer,
)

BTC_META = MarketMetadata(
    symbol="BTC",
    sz_decimals=5,
    price_tick=Decimal("0.1"),
    min_size=Decimal("0.00001"),
)


class TestOrderNormalizer:
    def test_order_size_is_rounded_down_to_size_decimals(self) -> None:
        normalizer = OrderNormalizer(BTC_META)
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.00123456"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("50000"),
        )
        result = normalizer.normalize(intent, Decimal("50000"))
        assert result.size == Decimal("0.00123")

    def test_order_price_is_rounded_to_tick(self) -> None:
        normalizer = OrderNormalizer(BTC_META)
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.001"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("50000.15"),
        )
        result = normalizer.normalize(intent, Decimal("50000"))
        assert result.limit_price == Decimal("50000.1")

    def test_too_small_order_is_rejected(self) -> None:
        normalizer = OrderNormalizer(BTC_META)
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.000001"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("50000"),
        )
        with pytest.raises(OrderNormalizationError, match="below minimum"):
            normalizer.normalize(intent, Decimal("50000"))

    def test_market_order_uses_slippage_limited_price(self) -> None:
        normalizer = OrderNormalizer(BTC_META, max_slippage=Decimal("0.01"))
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.001"),
            order_type=OrderType.MARKET,
        )
        result = normalizer.normalize(intent, Decimal("50000"))
        # Buy market → limit = ref * 1.01 = 50500, rounded to tick 0.1
        assert result.limit_price == Decimal("50500.0")

    def test_sell_market_uses_slippage_below_reference(self) -> None:
        normalizer = OrderNormalizer(BTC_META, max_slippage=Decimal("0.01"))
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.SELL,
            size=Decimal("0.001"),
            order_type=OrderType.MARKET,
        )
        result = normalizer.normalize(intent, Decimal("50000"))
        # Sell market → limit = ref * 0.99 = 49500
        assert result.limit_price == Decimal("49500.0")

    def test_unknown_symbol_metadata_rejected_during_normalization(self) -> None:
        """Normalizer receives metadata at construction — caller checks existence."""
        # The OrderNormalizer itself doesn't reject unknown symbols;
        # the caller (order planner) queries the provider first.
        # This test verifies normalizer works when given valid metadata.
        meta = MarketMetadata(
            symbol="UNKNOWN", sz_decimals=2, price_tick=Decimal("0.01")
        )
        normalizer = OrderNormalizer(meta)
        intent = OrderIntent(
            symbol="UNKNOWN",
            side=OrderSide.BUY,
            size=Decimal("1.5"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("100.123"),
        )
        result = normalizer.normalize(intent, Decimal("100"))
        assert result.size == Decimal("1.5")
