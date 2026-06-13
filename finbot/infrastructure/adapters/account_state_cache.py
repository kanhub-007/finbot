"""Account-state cache — keeps recent position/open-order state from the
exchange websocket so the candle hot path can read it without a REST call.

The :class:`HyperliquidExchangeGateway` hits REST for ``get_position`` and
``list_open_orders`` on every candle otherwise (1–2 network round-trips per
candle, 50–200 ms each). This cache is fed by the account websocket stream
(fills / order updates) and by successful order submissions, with a short
TTL so a stale entry falls back to a fresh REST fetch.

Thread-safe: written from the websocket thread, read from the candle thread.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot


class AccountStateCache:
    """In-memory cache of position and open-order state for one account.

    Parameters
    ----------
    ttl_seconds:
        Maximum age of a cached entry before it is considered stale and the
        caller falls back to a live fetch.  0 disables caching entirely.
    """

    def __init__(self, ttl_seconds: float = 5.0) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._positions: dict[str, PositionSnapshot] = {}
        self._position_updated_at: dict[str, float] = {}
        self._open_orders: dict[str, list[dict[str, Any]]] = {}
        self._open_orders_updated_at: dict[str, float] = {}

    # -- position ----------------------------------------------------------

    def get_position(self, symbol: str) -> PositionSnapshot | None:
        """Return a cached position if fresh enough, else None."""
        if self._ttl <= 0:
            return None
        sym = symbol.upper()
        with self._lock:
            updated = self._position_updated_at.get(sym, 0.0)
            if time.monotonic() - updated > self._ttl:
                return None
            return self._positions.get(sym)

    def set_position(self, snapshot: PositionSnapshot) -> None:
        with self._lock:
            sym = snapshot.symbol.upper()
            self._positions[sym] = snapshot
            self._position_updated_at[sym] = time.monotonic()

    def clear_position(self, symbol: str) -> None:
        with self._lock:
            sym = symbol.upper()
            self._positions.pop(sym, None)
            self._position_updated_at.pop(sym, None)

    # -- open orders -------------------------------------------------------

    def get_open_orders(self, symbol: str) -> list[dict[str, Any]] | None:
        if self._ttl <= 0:
            return None
        sym = symbol.upper()
        with self._lock:
            updated = self._open_orders_updated_at.get(sym, 0.0)
            if time.monotonic() - updated > self._ttl:
                return None
            return list(self._open_orders.get(sym, []))

    def set_open_orders(self, symbol: str, orders: list[dict[str, Any]]) -> None:
        with self._lock:
            sym = symbol.upper()
            self._open_orders[sym] = list(orders)
            self._open_orders_updated_at[sym] = time.monotonic()

    def add_open_order(self, symbol: str, order: dict[str, Any]) -> None:
        with self._lock:
            sym = symbol.upper()
            orders = list(self._open_orders.get(sym, []))
            orders.append(order)
            self._open_orders[sym] = orders
            self._open_orders_updated_at[sym] = time.monotonic()

    def remove_open_order(self, symbol: str, predicate) -> None:
        """Drop open orders for *symbol* matching *predicate(order) -> bool*."""
        with self._lock:
            sym = symbol.upper()
            if sym not in self._open_orders:
                return
            kept = [o for o in self._open_orders[sym] if not predicate(o)]
            self._open_orders[sym] = kept
            self._open_orders_updated_at[sym] = time.monotonic()

    # -- maintenance -------------------------------------------------------

    def clear(self) -> None:
        with self._lock:
            self._positions.clear()
            self._position_updated_at.clear()
            self._open_orders.clear()
            self._open_orders_updated_at.clear()


def flat_position(symbol: str) -> PositionSnapshot:
    """Return a zero-size FLAT position snapshot for *symbol*."""
    return PositionSnapshot(
        symbol=symbol, direction=PositionDirection.FLAT, size=Decimal("0")
    )
