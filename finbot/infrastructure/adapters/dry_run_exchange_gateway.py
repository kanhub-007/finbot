"""Dry-run exchange gateway implementation."""

from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.wallet_balance import WalletBalance
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

    def cancel_by_cloid(self, symbol: str, cloid: str) -> dict[str, Any]:
        """Return a synthetic cancellation response."""
        return {"status": "dry_run", "symbol": symbol, "cloid": cloid}

    def cancel_by_oid(self, symbol: str, oid: str) -> dict[str, Any]:
        """Return a synthetic cancellation response."""
        return {"status": "dry_run", "symbol": symbol, "oid": oid}

    def set_leverage(
        self, symbol: str, leverage: int, margin_mode: str = "isolated"
    ) -> dict[str, Any]:
        """No-op in dry-run; records nothing on the exchange."""
        return {"status": "dry_run", "symbol": symbol, "leverage": leverage}

    def get_leverage(self, symbol: str) -> tuple[int, str] | None:
        """Dry-run has no real exchange leverage; caller falls back to 1x."""
        return None

    def get_price(self, symbol: str) -> Decimal:
        """Synthetic price for offline dry-run."""
        return Decimal("100")

    def get_balance(self) -> WalletBalance:
        """Synthetic balance for dry-run."""
        return WalletBalance(
            wallet_value=Decimal("10000"),
            margin_used=Decimal("0"),
            available=Decimal("10000"),
        )

    def count_open_orders_cached(self, symbol: str) -> int | None:
        """Dry-run always has zero open orders (no websocket cache)."""
        return 0
