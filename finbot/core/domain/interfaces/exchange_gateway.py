"""Exchange execution interface."""

from abc import ABC, abstractmethod
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.position_snapshot import PositionSnapshot


class ExchangeGateway(ABC):
    """Abstracts exchange order and account operations."""

    @abstractmethod
    def get_position(self, symbol: str) -> PositionSnapshot:
        """Return the current exchange position for a symbol."""

    @abstractmethod
    def list_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        """Return open exchange orders for a symbol."""

    @abstractmethod
    def submit_order(self, intent: OrderIntent) -> dict[str, Any]:
        """Submit an order intent to the exchange."""

    @abstractmethod
    def cancel_all(self, symbol: str) -> dict[str, Any]:
        """Cancel all open orders for a symbol."""

    @abstractmethod
    def cancel_by_cloid(self, symbol: str, cloid: str) -> dict[str, Any]:
        """Cancel a single order by its client-assigned ID."""
