"""Tests for the AccountStateCache hot-path optimization.

Verifies that get_position / list_open_orders read the cache (O(1)) and
only fall back to REST on a cache miss, and that submissions/cancels and
websocket events keep the cache consistent.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.infrastructure.adapters.account_state_cache import AccountStateCache
from finbot.infrastructure.adapters.hyperliquid_exchange_gateway import (
    HyperliquidExchangeGateway,
)


class TestAccountStateCache:
    def test_get_position_returns_none_when_empty(self) -> None:
        cache = AccountStateCache(ttl_seconds=5)
        assert cache.get_position("BTC") is None

    def test_set_then_get_returns_cached_position(self) -> None:
        cache = AccountStateCache(ttl_seconds=5)
        snap = PositionSnapshot(
            symbol="BTC", direction=PositionDirection.LONG, size=Decimal("1")
        )
        cache.set_position(snap)
        got = cache.get_position("btc")  # case-insensitive
        assert got is not None
        assert got.size == Decimal("1")

    def test_expired_entry_returns_none(self) -> None:
        cache = AccountStateCache(ttl_seconds=0.01)
        cache.set_position(
            PositionSnapshot(
                symbol="BTC", direction=PositionDirection.LONG, size=Decimal("1")
            )
        )
        import time

        time.sleep(0.02)
        assert cache.get_position("BTC") is None

    def test_clear_position_invalidates_one_symbol(self) -> None:
        cache = AccountStateCache(ttl_seconds=5)
        cache.set_position(
            PositionSnapshot(
                symbol="BTC", direction=PositionDirection.LONG, size=Decimal("1")
            )
        )
        cache.clear_position("BTC")
        assert cache.get_position("BTC") is None

    def test_remove_open_order_filters_by_predicate(self) -> None:
        cache = AccountStateCache(ttl_seconds=5)
        cache.set_open_orders("BTC", [{"oid": "1"}, {"oid": "2"}])
        cache.remove_open_order("BTC", lambda o: o["oid"] == "1")
        orders = cache.get_open_orders("BTC")
        assert orders == [{"oid": "2"}]


class TestGatewayUsesCache:
    def _gateway(self) -> HyperliquidExchangeGateway:
        return HyperliquidExchangeGateway(private_key="0x" + "a" * 64)

    def test_get_position_caches_so_second_call_skips_rest(self) -> None:
        gateway = self._gateway()
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "assetPositions": [
                {"position": {"coin": "BTC", "szi": "0.5", "entryPx": "50000"}}
            ]
        }
        with patch.object(gateway, "_ensure_info", return_value=mock_info):
            first = gateway.get_position("BTC")
            second = gateway.get_position("BTC")

        assert first.size == Decimal("0.5")
        assert second.size == Decimal("0.5")
        # REST should be hit exactly once; the second call served from cache.
        assert mock_info.user_state.call_count == 1

    def test_list_open_orders_caches_so_second_call_skips_rest(self) -> None:
        gateway = self._gateway()
        mock_info = MagicMock()
        mock_info.open_orders.return_value = [{"coin": "BTC", "oid": "a"}]
        with patch.object(gateway, "_ensure_info", return_value=mock_info):
            gateway.list_open_orders("BTC")
            gateway.list_open_orders("BTC")

        assert mock_info.open_orders.call_count == 1

    def test_submit_order_adds_to_open_order_cache(self) -> None:
        gateway = self._gateway()
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = {"status": "ok"}
        with patch.object(gateway, "_ensure_exchange", return_value=mock_exchange):
            gateway.submit_order(
                OrderIntent(
                    symbol="BTC",
                    side=OrderSide.BUY,
                    size=Decimal("0.001"),
                    order_type=OrderType.MARKET,
                    cloid="c1",
                )
            )
        # The cache should now hold the new open order without a REST call.
        cached = gateway.account_cache().get_open_orders("BTC")
        assert cached is not None
        assert any(o.get("coin") == "BTC" for o in cached)

    def test_cancel_all_clears_cache(self) -> None:
        gateway = self._gateway()
        gateway.account_cache().set_open_orders("BTC", [{"oid": "x"}])
        mock_exchange = MagicMock()
        mock_info = MagicMock()
        mock_info.open_orders.return_value = [{"coin": "BTC", "oid": "x"}]
        mock_exchange.bulk_cancel.return_value = {"status": "ok"}
        with patch.object(gateway, "_ensure_exchange", return_value=mock_exchange):
            with patch.object(gateway, "_ensure_info", return_value=mock_info):
                gateway.cancel_all("BTC")
        assert gateway.account_cache().get_open_orders("BTC") is None
