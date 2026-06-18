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
from finbot.infrastructure.adapters.account_state_cache import AccountStateCache
from finbot.infrastructure.services.log_redactor import (
    validate_private_key,
)

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
        validate_private_key(private_key)
        self._private_key = private_key
        self._base_url = base_url
        self._account_address = account_address or None
        self._vault_address = vault_address or None
        self._repo = repo
        self._retry = retry_policy or RetryPolicy()
        self._exchange: Exchange | None = None
        self._info: Info | None = None
        # Hot-path cache for position/open-order state, fed by the account
        # websocket stream and by successful order submissions.  Defaults to
        # a short TTL so the candle loop reads the cache (O(1)) instead of a
        # REST round-trip per candle.
        self._account_cache = AccountStateCache(ttl_seconds=5.0)

    def account_cache(self) -> AccountStateCache:
        """Expose the account-state cache for the websocket stream to update."""
        return self._account_cache

    # -- ExchangeGateway ---------------------------------------------------

    def get_position(self, symbol: str) -> PositionSnapshot:
        cached = self._account_cache.get_position(symbol)
        if cached is not None:
            return cached
        snapshot = self._fetch_position(symbol)
        self._account_cache.set_position(snapshot)
        return snapshot

    def _fetch_position(self, symbol: str) -> PositionSnapshot:
        """Fetch the position from the exchange (REST) and normalise it."""
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
        cached = self._account_cache.get_open_orders(symbol)
        if cached is not None:
            return cached
        orders = self._fetch_open_orders(symbol)
        self._account_cache.set_open_orders(symbol, orders)
        return orders

    def _fetch_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch open orders from the exchange (REST) filtered by symbol."""
        info = self._ensure_info()
        orders = info.open_orders(self._account_address or "")
        result = []
        for o in orders:
            if o.get("coin", "").upper() == symbol.upper():
                result.append(o)
        return result

    def submit_order(self, intent: OrderIntent) -> dict[str, Any]:
        exchange = self._ensure_exchange()

        def _submit() -> dict[str, Any]:
            return _execute_order(exchange, intent)

        result = self._retry.execute(_submit, require_cloid=intent.cloid or "")
        # Optimistically record the new open order in the cache so the next
        # candle's list_open_orders() needn't re-fetch over REST.
        if result.get("status") in ("ok", "success") and not intent.reduce_only:
            self._account_cache.add_open_order(
                intent.symbol, {"coin": intent.symbol, "side": intent.side.value}
            )
        # Persistence (intent + response) is the application layer's
        # responsibility (OrderSubmitter / the runtime) — recording here too
        # would duplicate every intent and response row.
        return result

    def cancel_all(self, symbol: str) -> dict[str, Any]:
        exchange = self._ensure_exchange()
        # A kill switch must operate on authoritative exchange state, not the
        # account cache: cached entries from submit_order omit "oid" and would
        # cause bulk_cancel([]) to silently no-op.  Always fetch fresh.
        open_orders = self._fetch_open_orders(symbol)
        if not open_orders:
            self._account_cache.clear()
            return {"status": "ok", "cancelled": 0}
        # Use bulk_cancel for efficiency.
        cancels = [{"coin": symbol, "oid": o["oid"]} for o in open_orders if "oid" in o]
        result = exchange.bulk_cancel(cancels)  # type: ignore[no-any-return]
        self._account_cache.clear()
        return result

    def cancel_by_cloid(self, symbol: str, cloid: str) -> dict[str, Any]:
        exchange = self._ensure_exchange()
        result = exchange.cancel_by_cloid(symbol, cloid)  # type: ignore[no-any-return]
        self._account_cache.remove_open_order(symbol, lambda o: o.get("cloid") == cloid)
        return result

    def cancel_by_oid(self, symbol: str, oid: str) -> dict[str, Any]:
        """Cancel a single order by its exchange-assigned ID."""
        exchange = self._ensure_exchange()
        result = exchange.cancel(symbol, oid)  # type: ignore[no-any-return]
        self._account_cache.remove_open_order(symbol, lambda o: str(o.get("oid", "")) == oid)
        return result

    # -- leverage / market data (trading-control spec) ---------------------

    def set_leverage(
        self, symbol: str, leverage: int, margin_mode: str = "isolated"
    ) -> dict[str, Any]:
        """Set leverage and margin mode for a symbol via the SDK."""
        exchange = self._ensure_exchange()
        is_cross = margin_mode.lower() == "cross"
        return exchange.update_leverage(  # type: ignore[no-any-return]
            leverage=int(leverage), coin=symbol, is_cross=is_cross
        )

    def get_leverage(self, symbol: str) -> tuple[int, str] | None:
        """Read current leverage and margin mode for a symbol.

        Hyperliquid exposes per-asset leverage in ``user_state`` under
        ``assetPositions``. Returns ``(leverage, margin_mode)`` or None.
        """
        try:
            info = self._ensure_info()
            state = info.user_state(self._account_address or "")
            positions = state.get("assetPositions", [])
            for pos in positions:
                pos_info = pos.get("position", {})
                if pos_info.get("coin", "").upper() == symbol.upper():
                    leverage = int(pos_info.get("leverage", {}).get("value", 1))
                    is_cross = (
                        pos_info.get("leverage", {}).get("type", "cross").lower()
                        == "cross"
                    )
                    return leverage, ("cross" if is_cross else "isolated")
            return None
        except Exception:
            return None

    def get_price(self, symbol: str) -> Decimal:
        """Return the current mark/mid price via ``all_mids``."""
        info = self._ensure_info()
        mids = info.all_mids()
        price = mids.get(symbol, mids.get(symbol.upper(), "0"))
        return Decimal(str(price))

    def get_balance(self) -> WalletBalance:
        """Return wallet value, margin used, and available margin."""
        info = self._ensure_info()
        state = info.user_state(self._account_address or "")
        margin_summary = state.get("marginSummary", {})
        wallet_value = Decimal(str(margin_summary.get("accountValue", "0")))
        margin_used = Decimal(str(margin_summary.get("initialMargin", "0")))
        available = Decimal(str(margin_summary.get("availableMargin", "0")))
        return WalletBalance(
            wallet_value=wallet_value,
            margin_used=margin_used,
            available=available,
        )

    def get_exchange(self) -> Exchange:
        """Return the underlying SDK ``Exchange`` (lazy-initialised).

        Used to share the authenticated websocket manager with the
        :class:`HyperliquidAccountDataStream` so account subscriptions and
        order submission use one signing context.
        """
        return self._ensure_exchange()

    # -- internal -----------------------------------------------------------

    def _ensure_exchange(self) -> Exchange:
        if self._exchange is None:
            from eth_account import Account
            from hyperliquid.exchange import Exchange

            wallet = Account.from_key(self._private_key)
            self._exchange = Exchange(
                wallet=wallet,
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
