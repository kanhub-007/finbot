"""Tests for HyperliquidExchangeGateway using mocked SDK."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.infrastructure.adapters.hyperliquid_exchange_gateway import (
    HyperliquidExchangeGateway,
)
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)


class TestHyperliquidExchangeGateway:
    def test_market_entry_maps_to_sdk_market_open(self) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = {
            "status": "ok",
            "response": {"type": "order", "data": {}},
        }

        with patch.object(
            HyperliquidExchangeGateway,
            "_ensure_exchange",
            return_value=mock_exchange,
        ):
            gateway = HyperliquidExchangeGateway(
                private_key="0x" + "a" * 64,
                base_url="https://testnet",
            )
            intent = OrderIntent(
                symbol="BTC",
                side=OrderSide.BUY,
                size=Decimal("0.001"),
                order_type=OrderType.MARKET,
                cloid="cloid-1",
            )
            result = gateway.submit_order(intent)
            mock_exchange.market_open.assert_called_once_with(
                coin="BTC",
                is_buy=True,
                sz=0.001,
                limit_px=None,
                cloid="cloid-1",
            )
            assert result["status"] == "ok"

    def test_exit_order_is_reduce_only(self) -> None:
        mock_exchange = MagicMock()
        mock_exchange.market_close.return_value = {
            "status": "ok",
            "response": {"type": "order", "data": {}},
        }

        with patch.object(
            HyperliquidExchangeGateway,
            "_ensure_exchange",
            return_value=mock_exchange,
        ):
            gateway = HyperliquidExchangeGateway(
                private_key="0x" + "a" * 64,
            )
            intent = OrderIntent(
                symbol="BTC",
                side=OrderSide.SELL,
                size=Decimal("0.001"),
                order_type=OrderType.MARKET,
                reduce_only=True,
                cloid="cloid-exit",
            )
            result = gateway.submit_order(intent)
            mock_exchange.market_close.assert_called_once_with(
                coin="BTC",
                sz=0.001,
            )
            assert result["status"] == "ok"

    def test_cancel_by_cloid_maps_to_sdk(self) -> None:
        mock_exchange = MagicMock()
        mock_exchange.cancel_by_cloid.return_value = {
            "status": "ok",
        }

        with patch.object(
            HyperliquidExchangeGateway,
            "_ensure_exchange",
            return_value=mock_exchange,
        ):
            gateway = HyperliquidExchangeGateway(
                private_key="0x" + "a" * 64,
            )
            result = gateway.cancel_by_cloid("BTC", "cloid-1")
            mock_exchange.cancel_by_cloid.assert_called_once_with("BTC", "cloid-1")
            assert result["status"] == "ok"

    def test_gateway_does_not_persist_submission(self) -> None:
        """The gateway is a pure execution adapter — persistence is the
        application layer's job (OrderSubmitter), so submit_order must NOT
        record intents or responses (would duplicate every row)."""
        repo = InMemoryBotStateRepository()
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = {
            "status": "ok",
            "response": {"type": "order", "data": {}},
        }

        with patch.object(
            HyperliquidExchangeGateway,
            "_ensure_exchange",
            return_value=mock_exchange,
        ):
            gateway = HyperliquidExchangeGateway(
                private_key="0x" + "a" * 64,
                repo=repo,
            )
            intent = OrderIntent(
                symbol="BTC",
                side=OrderSide.BUY,
                size=Decimal("0.001"),
                order_type=OrderType.MARKET,
                cloid="cloid-1",
            )
            result = gateway.submit_order(intent)

            # The response is returned to the caller for it to persist.
            assert result["status"] == "ok"
            # The gateway must not persist anything itself.
            assert len(repo._responses) == 0

    def test_reconciliation_detects_position_mismatch(self) -> None:
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "0.001",
                        "entryPx": "50000",
                    }
                }
            ]
        }

        with patch.object(
            HyperliquidExchangeGateway,
            "_ensure_info",
            return_value=mock_info,
        ):
            gateway = HyperliquidExchangeGateway(
                private_key="0x" + "a" * 64,
            )
            pos = gateway.get_position("BTC")
            assert pos.direction.value == "long"
            assert pos.size == Decimal("0.001")
            assert pos.entry_price == Decimal("50000")

    def test_no_position_returns_flat(self) -> None:
        mock_info = MagicMock()
        mock_info.user_state.return_value = {"assetPositions": []}

        with patch.object(
            HyperliquidExchangeGateway,
            "_ensure_info",
            return_value=mock_info,
        ):
            gateway = HyperliquidExchangeGateway(
                private_key="0x" + "a" * 64,
            )
            pos = gateway.get_position("ETH")
            assert pos.direction.value == "flat"
            assert pos.size == Decimal("0")

    def test_hip3_symbol_passed_through_to_sdk(self) -> None:
        """HIP-3 dex:COIN symbols are passed directly to the SDK."""
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = {
            "status": "ok",
            "response": {"type": "order", "data": {}},
        }

        with patch.object(
            HyperliquidExchangeGateway,
            "_ensure_exchange",
            return_value=mock_exchange,
        ):
            gateway = HyperliquidExchangeGateway(
                private_key="0x" + "a" * 64,
            )
            intent = OrderIntent(
                symbol="xyz:AAPL",
                side=OrderSide.BUY,
                size=Decimal("0.01"),
                order_type=OrderType.MARKET,
                cloid="cloid-hip3",
            )
            result = gateway.submit_order(intent)
            mock_exchange.market_open.assert_called_once_with(
                coin="xyz:AAPL",
                is_buy=True,
                sz=0.01,
                limit_px=None,
                cloid="cloid-hip3",
            )
            assert result["status"] == "ok"

    def test_hip3_position_query_uses_raw_symbol(self) -> None:
        """Position query for HIP-3 tokens uses dex:COIN format."""
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "flx:TSLA",
                        "szi": "0.5",
                        "entryPx": "410.00",
                    }
                }
            ]
        }

        with patch.object(
            HyperliquidExchangeGateway,
            "_ensure_info",
            return_value=mock_info,
        ):
            gateway = HyperliquidExchangeGateway(
                private_key="0x" + "a" * 64,
            )
            pos = gateway.get_position("flx:TSLA")
            assert pos.direction.value == "long"
            assert pos.size == Decimal("0.5")
            assert pos.entry_price == Decimal("410.00")

    def test_hip3_cancel_by_cloid(self) -> None:
        """Cancel by cloid passes HIP-3 symbol through."""
        mock_exchange = MagicMock()
        mock_exchange.cancel_by_cloid.return_value = {"status": "ok"}

        with patch.object(
            HyperliquidExchangeGateway,
            "_ensure_exchange",
            return_value=mock_exchange,
        ):
            gateway = HyperliquidExchangeGateway(
                private_key="0x" + "a" * 64,
            )
            result = gateway.cancel_by_cloid("xyz:AAPL", "cloid-1")
            mock_exchange.cancel_by_cloid.assert_called_once_with("xyz:AAPL", "cloid-1")
            assert result["status"] == "ok"

    def test_cancel_all_calls_bulk_cancel(self) -> None:
        mock_exchange = MagicMock()
        mock_exchange.bulk_cancel.return_value = {"status": "ok"}

        mock_info = MagicMock()
        mock_info.open_orders.return_value = [
            {"coin": "BTC", "oid": 123},
            {"coin": "BTC", "oid": 456},
        ]

        with (
            patch.object(
                HyperliquidExchangeGateway,
                "_ensure_exchange",
                return_value=mock_exchange,
            ),
            patch.object(
                HyperliquidExchangeGateway,
                "_ensure_info",
                return_value=mock_info,
            ),
        ):
            gateway = HyperliquidExchangeGateway(
                private_key="0x" + "a" * 64,
            )
            result = gateway.cancel_all("BTC")
            mock_exchange.bulk_cancel.assert_called_once_with(
                [
                    {"coin": "BTC", "oid": 123},
                    {"coin": "BTC", "oid": 456},
                ]
            )
            assert result["status"] == "ok"


def test_cancel_all_bypasses_cache_to_cancel_real_orders() -> None:
    """C1: cancel_all must fetch fresh (with oid), not trust oid-less cache."""
    repo = InMemoryBotStateRepository()
    mock_exchange = MagicMock()
    mock_exchange.open_orders.return_value = [{"coin": "BTC", "oid": 42}]
    mock_exchange.bulk_cancel.return_value = {"status": "ok", "cancelled": 1}

    with (
        patch.object(
            HyperliquidExchangeGateway, "_ensure_info", return_value=mock_exchange
        ),
        patch.object(
            HyperliquidExchangeGateway, "_ensure_exchange", return_value=mock_exchange
        ),
    ):
        gateway = HyperliquidExchangeGateway(private_key="0x" + "a" * 64, repo=repo)
        # Poison the cache with an oid-less entry (as submit_order does).
        gateway.account_cache().add_open_order("BTC", {"coin": "BTC", "side": "buy"})

        result = gateway.cancel_all("BTC")

        # bulk_cancel must have received the real oid from a fresh fetch.
        mock_exchange.bulk_cancel.assert_called_once_with([{"coin": "BTC", "oid": 42}])
        assert result["cancelled"] == 1
