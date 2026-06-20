"""Tests for HyperliquidExchangeGateway order-precision boundary (S5: M6).

Deviation from the spec's literal Verify block
----------------------------------------------
The spec's scenario S5 says "the SDK receives ``str(size)`` and
``str(limit_price)``". This is **impossible** with the installed
Hyperliquid SDK: ``exchange.order()`` → ``order_request_to_order_wire`` →
``float_to_wire(x)`` runs ``f"{x:.8f}"`` and ``abs(float(rounded) - x) >=
1e-12``. Passing a ``str`` raises ``ValueError: Unknown format code 'f'
for object of type 'str'``; passing a ``Decimal`` raises ``TypeError`` at
the ``float(rounded) - x`` subtraction. The SDK fundamentally requires a
``float`` and enforces ≤8 significant decimals itself.

Real precision protection therefore lives at two upstream layers:
  1. ``OrderNormalizer`` rounds size/price to the symbol's ``sz_decimals``
     / ``price_tick`` before the intent reaches the gateway.
  2. ``float_to_wire`` rejects any float whose 8-decimal rounding loses
     precision (``>= 1e-12``), so an un-normalised value fails loudly.

What ``_execute_order`` must guarantee is that it does **not** add its own
rounding loss on top of those layers, and that it fails loudly on a
malformed intent (e.g. a LIMIT order with no price) instead of silently
submitting ``limit_px=0.0``. These tests pin that contract.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.infrastructure.adapters.hyperliquid_exchange_gateway import (
    HyperliquidExchangeGateway,
    _execute_order,
)


class _FakeExchange:
    """Records every SDK call's positional/kw args."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def order(self, name: str, is_buy: bool, sz: float, limit_px: float, **kw):
        self.calls.append(("order", (name, is_buy, sz, limit_px), kw))
        return {"status": "ok"}

    def market_open(
        self,
        name: str,
        is_buy: bool,
        sz: float,
        px=None,
        slippage=0.05,
        cloid=None,
        builder=None,
    ):
        self.calls.append(
            ("market_open", (name, is_buy, sz), {"px": px, "cloid": cloid})
        )
        return {"status": "ok"}

    def market_close(self, coin: str, sz=None, **kw):
        self.calls.append(("market_close", (coin,), {"sz": sz, **kw}))
        return {"status": "ok"}


def _gateway_with_fake_exchange():
    gw = HyperliquidExchangeGateway(private_key="0x" + "a" * 64, base_url="x")
    gw._exchange = _FakeExchange()
    return gw


class TestExecuteOrderPrecisionBoundary:
    def test_limit_order_size_and_price_round_trip_through_float(self) -> None:
        """A normalised LIMIT order's sz/limit_px must round-trip exactly.

        ``Decimal(str(float(value))) == value`` proves ``_execute_order``
        introduced no extra rounding beyond float's faithful representation
        of an already-≤8-decimal value.
        """
        gw = _gateway_with_fake_exchange()
        size = Decimal("0.12345678")  # 8 decimals — within float precision
        price = Decimal("94000.12345678")  # 14 sig digits — within float
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=size,
            order_type=OrderType.LIMIT,
            limit_price=price,
            cloid="c-1",
        )

        gw.submit_order(intent)

        name, (_, is_buy, sz, limit_px), kw = gw._exchange.calls[0]
        assert name == "order"
        assert Decimal(str(sz)) == size
        assert Decimal(str(limit_px)) == price
        assert is_buy is True
        assert kw["reduce_only"] is False

    def test_limit_order_with_no_price_raises_not_silently_zero(
        self,
    ) -> None:
        """A LIMIT order with ``limit_price=None`` must raise, not submit a
        ``$0`` limit order (the prior ``if intent.limit_price else 0.0``
        pattern silently submitted limit_px=0.0)."""
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.1"),
            order_type=OrderType.LIMIT,
            limit_price=None,
            cloid="c-1",
        )
        fake = _FakeExchange()
        with pytest.raises((ValueError, TypeError)):
            _execute_order(fake, intent)
        # No call was recorded because the conversion raised before any SDK call.
        assert fake.calls == [] or fake.calls[0][2].get("limit_px") != 0.0

    def test_market_order_passes_none_limit_px_to_market_open(self) -> None:
        """MARKET entry with no price passes ``limit_px=None`` (not 0.0)."""
        gw = _gateway_with_fake_exchange()
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.1"),
            order_type=OrderType.MARKET,
            cloid="c-1",
        )
        gw.submit_order(intent)
        name, (_, is_buy, _sz), kw = gw._exchange.calls[0]
        assert name == "market_open"
        assert kw["px"] is None
        assert is_buy is True

    def test_reduce_only_limit_passes_reduce_only_and_cloid(self) -> None:
        """A reduce-only LIMIT order passes ``reduce_only=True`` and cloid."""
        gw = _gateway_with_fake_exchange()
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.SELL,
            size=Decimal("0.1"),
            order_type=OrderType.LIMIT,
            reduce_only=True,
            limit_price=Decimal("95000"),
            cloid="SL:BTC",
        )
        gw.submit_order(intent)
        name, (_, is_buy, _sz, _limit_px), kw = gw._exchange.calls[0]
        assert name == "order"
        assert kw["reduce_only"] is True
        assert is_buy is False
        assert kw["cloid"] is not None  # converted to Cloid by gateway

    def test_reduce_only_market_uses_market_close(self) -> None:
        """A reduce-only MARKET order routes to ``market_close``."""
        gw = _gateway_with_fake_exchange()
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.SELL,
            size=Decimal("0.1"),
            order_type=OrderType.MARKET,
            reduce_only=True,
            cloid="c-1",
        )
        gw.submit_order(intent)
        name, _args, kw = gw._exchange.calls[0]
        assert name == "market_close"
        assert Decimal(str(kw.get("sz", "0"))) == Decimal("0.1")
