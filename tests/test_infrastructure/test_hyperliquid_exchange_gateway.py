"""Tests for HyperliquidExchangeGateway placeholder."""

from decimal import Decimal

import pytest

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.infrastructure.adapters.hyperliquid_exchange_gateway import (
    HyperliquidExchangeGateway,
)


class TestHyperliquidExchangeGateway:
    def setup_method(self) -> None:
        self.gateway = HyperliquidExchangeGateway()

    def test_get_position_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="pending"):
            self.gateway.get_position("BTC")

    def test_list_open_orders_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="pending"):
            self.gateway.list_open_orders("BTC")

    def test_submit_order_raises_not_implemented(self) -> None:
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.001"),
            order_type=OrderType.LIMIT,
        )
        with pytest.raises(NotImplementedError, match="pending"):
            self.gateway.submit_order(intent)

    def test_cancel_all_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="pending"):
            self.gateway.cancel_all("BTC")
