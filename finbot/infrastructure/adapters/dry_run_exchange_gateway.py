"""Dry-run exchange gateway implementation."""

from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway


class DryRunExchangeGateway(ExchangeGateway):
    """Exchange gateway that records intent without placing live orders."""

    def get_position(self, symbol: str) -> PositionSnapshot:
        """Return an empty synthetic position for dry-run mode."""
        return PositionSnapshot(
            symbol=symbol, direction=PositionDirection.FLAT, size=Decimal("0")
        )

    def list_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        """Return no open orders in dry-run mode."""
        return []

    def submit_order(self, intent: OrderIntent) -> dict[str, Any]:
        """Return a synthetic order response without external side effects."""
        return {"status": "dry_run", "symbol": intent.symbol, "side": intent.side}

    def cancel_all(self, symbol: str) -> dict[str, Any]:
        """Return a synthetic cancellation response."""
        return {"status": "dry_run", "symbol": symbol, "cancelled": 0}
