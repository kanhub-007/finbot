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

    def test_exchange_response_is_persisted(self) -> None:
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
            gateway.submit_order(intent)

            # Verify the response was persisted
            assert len(repo._responses) >= 1

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
