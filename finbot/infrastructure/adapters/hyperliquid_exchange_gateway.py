"""Hyperliquid exchange gateway implementation placeholder."""

from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway


class HyperliquidExchangeGateway(ExchangeGateway):
    """Exchange gateway backed by the Hyperliquid Python SDK.

    This skeleton intentionally avoids live order implementation until risk
    gates, idempotency, persistence, and testnet tests are in place.
    """

    def get_position(self, symbol: str) -> PositionSnapshot:
        """Return the current exchange position for a symbol."""
        raise NotImplementedError("Hyperliquid position reconciliation pending")

    def list_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        """Return current open orders for a symbol."""
        raise NotImplementedError("Hyperliquid order reconciliation pending")

    def submit_order(self, intent: OrderIntent) -> dict[str, Any]:
        """Submit an order to Hyperliquid after application risk checks."""
        raise NotImplementedError("Hyperliquid execution pending")

    def cancel_all(self, symbol: str) -> dict[str, Any]:
        """Cancel all open Hyperliquid orders for a symbol."""
        raise NotImplementedError("Hyperliquid cancellation pending")
