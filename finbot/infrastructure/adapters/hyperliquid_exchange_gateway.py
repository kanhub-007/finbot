"""Hyperliquid exchange gateway — live order execution and reconciliation.

Wraps the Hyperliquid SDK ``Exchange`` and ``Info`` classes to
implement the ``ExchangeGateway`` domain interface.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.position_direction import (
    PositionDirection,
)
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.services.retry_policy import RetryPolicy

if TYPE_CHECKING:
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info


class HyperliquidExchangeGateway(ExchangeGateway):
    """Live Hyperliquid order execution and reconciliation.

    Parameters
    ----------
    private_key:
        Wallet private key for signing orders.
    base_url:
        Hyperliquid API base URL (mainnet or testnet).
    account_address:
        Optional account address if trading via sub-account.
    vault_address:
        Optional vault address.
    repo:
        Bot state repository for persisting exchange responses.
    """

    def __init__(
        self,
        private_key: str,
        base_url: str = "https://api.hyperliquid.xyz",
        account_address: str = "",
        vault_address: str = "",
        repo: BotStateRepository | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._private_key = private_key
        self._base_url = base_url
        self._account_address = account_address or None
        self._vault_address = vault_address or None
        self._repo = repo
        self._retry = retry_policy or RetryPolicy()
        self._exchange: Exchange | None = None
        self._info: Info | None = None

    # -- ExchangeGateway ---------------------------------------------------

    def get_position(self, symbol: str) -> PositionSnapshot:
        info = self._ensure_info()
        state = info.user_state(self._account_address or "")
        positions = state.get("assetPositions", [])
        for pos in positions:
            pos_info = pos.get("position", {})
            coin = pos_info.get("coin", "")
            if coin.upper() == symbol.upper():
                size = Decimal(str(pos_info.get("szi", 0)))
                direction = (
                    PositionDirection.LONG
                    if size > 0
                    else PositionDirection.SHORT if size < 0 else PositionDirection.FLAT
                )
                entry_px = Decimal(str(pos_info.get("entryPx", 0)))
                return PositionSnapshot(
                    symbol=coin,
                    direction=direction,
                    size=abs(size),
                    entry_price=entry_px,
                )
        return PositionSnapshot(
            symbol=symbol,
            direction=PositionDirection.FLAT,
            size=Decimal("0"),
        )

    def list_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        info = self._ensure_info()
        orders = info.open_orders(self._account_address or "")
        result = []
        for o in orders:
            if o.get("coin", "").upper() == symbol.upper():
                result.append(o)
        return result

    def submit_order(self, intent: OrderIntent) -> dict[str, Any]:
        exchange = self._ensure_exchange()
        intent_id = self._repo.record_order_intent(intent) if self._repo else ""

        def _submit() -> dict[str, Any]:
            return _execute_order(exchange, intent)

        result = self._retry.execute(_submit, require_cloid=intent.cloid or "")
        if self._repo:
            import json

            from finbot.core.domain.entities.order_response_record import (
                OrderResponseRecord,
            )

            self._repo.record_order_response(
                OrderResponseRecord(
                    intent_id=intent_id,
                    bot_run_id="",
                    response_json=json.dumps(result),
                    status=result.get("status", "unknown"),
                )
            )
        return result

    def cancel_all(self, symbol: str) -> dict[str, Any]:
        exchange = self._ensure_exchange()
        # Collect open orders for the symbol and cancel them.
        open_orders = self.list_open_orders(symbol)
        if not open_orders:
            return {"status": "ok", "cancelled": 0}
        # Use bulk_cancel for efficiency.
        cancels = [{"coin": symbol, "oid": o["oid"]} for o in open_orders]
        return exchange.bulk_cancel(cancels)  # type: ignore[no-any-return]

    def cancel_by_cloid(self, symbol: str, cloid: str) -> dict[str, Any]:
        exchange = self._ensure_exchange()
        return exchange.cancel_by_cloid(symbol, cloid)  # type: ignore[no-any-return]

    # -- internal -----------------------------------------------------------

    def _ensure_exchange(self) -> Exchange:
        if self._exchange is None:
            from hyperliquid.exchange import Exchange

            class _Wallet:
                def __init__(self, pk: str, addr: str | None) -> None:
                    self._pk = pk
                    self._addr = addr

            self._exchange = Exchange(
                wallet=self._private_key,  # type: ignore[arg-type]
                base_url=self._base_url,
                account_address=self._account_address,
                vault_address=self._vault_address,
            )
        return self._exchange

    def _ensure_info(self) -> Info:
        if self._info is None:
            from hyperliquid.info import Info

            self._info = Info(self._base_url, skip_ws=True)
        return self._info


def _execute_order(
    exchange: Exchange,
    intent: OrderIntent,
) -> dict[str, Any]:
    """Map an OrderIntent to the appropriate SDK call."""
    is_buy = intent.side == OrderSide.BUY

    if intent.reduce_only:
        if intent.order_type == OrderType.MARKET:
            return exchange.market_close(
                coin=intent.symbol,
                sz=float(intent.size),
            )  # type: ignore[no-any-return]
        # Limit exit — use limit order with reduce_only.
        return exchange.order(
            coin=intent.symbol,
            is_buy=is_buy,
            sz=float(intent.size),
            limit_px=(float(intent.limit_price) if intent.limit_price else 0.0),
            order_type={"limit": {"tif": "Gtc"}},
            reduce_only=True,
            cloid=intent.cloid,
        )  # type: ignore[no-any-return]

    if intent.order_type == OrderType.MARKET:
        return exchange.market_open(
            coin=intent.symbol,
            is_buy=is_buy,
            sz=float(intent.size),
            limit_px=(float(intent.limit_price) if intent.limit_price else None),
            cloid=intent.cloid,
        )  # type: ignore[no-any-return]

    # Limit order.
    payload: dict[str, Any] = {
        "coin": intent.symbol,
        "is_buy": is_buy,
        "sz": float(intent.size),
        "limit_px": (float(intent.limit_price) if intent.limit_price else 0.0),
        "order_type": {"limit": {"tif": "Gtc"}},
        "reduce_only": intent.reduce_only,
    }
    if intent.cloid:
        payload["cloid"] = intent.cloid
    return exchange.order(**payload)  # type: ignore[no-any-return]
