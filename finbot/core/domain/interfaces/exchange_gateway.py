"""Exchange execution interface."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.wallet_balance import WalletBalance


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

    @abstractmethod
    def cancel_by_oid(self, symbol: str, oid: str) -> dict[str, Any]:
        """Cancel a single order by its exchange-assigned ID.

        Used by /cancel.
        """
        ...

    # -- leverage / market data (trading-control spec) ---------------------

    @abstractmethod
    def set_leverage(
        self, symbol: str, leverage: int, margin_mode: str = "isolated"
    ) -> dict[str, Any]:
        """Set leverage and margin mode for a symbol."""
        ...

    @abstractmethod
    def get_leverage(self, symbol: str) -> tuple[int, str] | None:
        """Read current leverage and margin mode for a symbol.

        Returns ``(leverage, margin_mode)`` or ``None`` if the exchange does
        not expose it (caller falls back to 1x isolated).
        """
        ...

    @abstractmethod
    def get_price(self, symbol: str) -> Decimal:
        """Return the current mark/mid price for a symbol."""
        ...

    @abstractmethod
    def get_balance(self) -> WalletBalance:
        """Return wallet value, margin used, and available margin."""
        ...
