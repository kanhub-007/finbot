"""RiskOrderService — attach/clear stop-loss and take-profit trigger orders.

Reduce-only SL/TP orders use a cloid scheme (``SL:<symbol>``,
``TP:<symbol>``) so they can be replaced atomically. Validates prices are
on the correct side of entry before placing.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.services.bot_manager.bot_manager_lock import (
    BotManagerLock,
)
from finbot.core.domain.services.bot_manager.bot_manager_state import (
    BotManagerState,
)

logger = logging.getLogger(__name__)


def resolve_risk_price(
    price: Decimal | str, entry: Decimal, kind: str, is_long: bool
) -> Decimal:
    """Resolve an SL/TP price from absolute or percentage input.

    ``"2%"`` is interpreted relative to entry; absolute prices are used as-is.
    """
    price_str = str(price).strip()
    if price_str.endswith("%"):
        pct = Decimal(price_str[:-1])
        if kind == "SL":
            factor = (
                Decimal("1") - (pct / Decimal("100"))
                if is_long
                else Decimal("1") + (pct / Decimal("100"))
            )
        else:  # TP
            factor = (
                Decimal("1") + (pct / Decimal("100"))
                if is_long
                else Decimal("1") - (pct / Decimal("100"))
            )
        return entry * factor
    return Decimal(price_str)


class RiskOrderService:
    """Attach, replace, and clear reduce-only SL/TP trigger orders."""

    def __init__(
        self,
        state: BotManagerState,
        lock: BotManagerLock,
        exchange: ExchangeGateway | None,
    ) -> None:
        self._state = state
        self._lock = lock
        self._exchange = exchange

    def attach_stop_loss(self, price: Decimal | str) -> dict[str, Any]:
        """Attach a reduce-only stop-loss trigger (cloid SL:<symbol>)."""
        return self._attach_risk_order("SL", price)

    def attach_take_profit(self, price: Decimal | str) -> dict[str, Any]:
        """Attach a reduce-only take-profit trigger (cloid TP:<symbol>)."""
        return self._attach_risk_order("TP", price)

    def clear_risk_order(self, kind: str) -> dict[str, Any]:
        """Cancel an SL or TP trigger order by kind ('sl' or 'tp')."""
        prefix = {"sl": "SL:", "tp": "TP:"}.get(kind.lower())
        if prefix is None:
            return {"status": "rejected", "message": f"Unknown kind: {kind}"}
        with self._lock:
            if self._state.active_symbol is None:
                return {"status": "rejected", "message": "No active symbol."}
            symbol = self._state.active_symbol.symbol
        cloid = f"{prefix}{symbol}"
        try:
            self._exchange.cancel_by_cloid(symbol, cloid)  # type: ignore[union-attr]
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        return {"status": "ok", "kind": kind, "symbol": symbol}

    def clear_risk_orders_for_symbol(self, symbol: str) -> None:
        """Cancel both SL and TP trigger orders for a symbol.

        Failures are logged, not raised, so a position close never fails due
        to cleanup. Called by ManualOrderService when closing/clearing.
        """
        if self._exchange is None:
            return
        for prefix in ("SL:", "TP:"):
            cloid = f"{prefix}{symbol}"
            try:
                self._exchange.cancel_by_cloid(symbol, cloid)
            except Exception:
                logger.warning("Failed to cancel risk order %s", cloid)

    def _attach_risk_order(self, kind: str, price: Decimal | str) -> dict[str, Any]:
        """Shared SL/TP attachment: validate, cancel existing, place new."""
        with self._lock:
            if self._state.active_symbol is None:
                return {
                    "status": "rejected",
                    "message": "No active symbol. Use /symbol first.",
                }
            if self._state.runtime is not None:
                return {
                    "status": "rejected",
                    "message": "A strategy is running. Stop it first (/stop).",
                }
            symbol = self._state.active_symbol.symbol
        if self._exchange is None:
            return {"status": "error", "message": "No exchange gateway wired"}
        pos = self._exchange.get_position(symbol)
        if pos is None or pos.direction.value == "flat":
            return {
                "status": "rejected",
                "message": f"No open position on {symbol} to protect.",
            }

        entry = pos.entry_price or Decimal("0")
        is_long = pos.direction == PositionDirection.LONG
        price_dec = resolve_risk_price(price, entry, kind, is_long)

        if kind == "SL":
            if is_long and price_dec >= entry:
                return {
                    "status": "rejected",
                    "message": "Stop must be below entry for a long.",
                }
            if not is_long and price_dec <= entry:
                return {
                    "status": "rejected",
                    "message": "Stop must be above entry for a short.",
                }
            order_type = OrderType.STOP
        else:  # TP
            if is_long and price_dec <= entry:
                return {
                    "status": "rejected",
                    "message": "Take-profit must be above entry for a long.",
                }
            if not is_long and price_dec >= entry:
                return {
                    "status": "rejected",
                    "message": "Take-profit must be below entry for a short.",
                }
            order_type = OrderType.TAKE_PROFIT
        side = OrderSide.SELL if is_long else OrderSide.BUY

        cloid = f"{kind}:{symbol}"
        try:
            self._exchange.cancel_by_cloid(symbol, cloid)  # replace existing
        except Exception:
            logger.warning("No existing %s order to replace for %s", kind, symbol)

        intent = OrderIntent(
            symbol=symbol,
            side=side,
            size=pos.size,
            order_type=order_type,
            reduce_only=True,
            limit_price=price_dec,
            cloid=cloid,
        )
        try:
            response = self._exchange.submit_order(intent)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        return {
            "status": "ok",
            "kind": kind.lower(),
            "symbol": symbol,
            "price": str(price_dec),
            "response": response,
        }
