"""SymbolSessionService — active symbol, leverage, price, position, orders.

Owns the :class:`ActiveSymbolState` (the currently selected trading
symbol + its leverage/margin mode). Reads positions/orders/balance from
the exchange. Activate does NOT set leverage — it reads the current
exchange leverage so it survives restarts.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.active_symbol_state import ActiveSymbolState
from finbot.core.domain.entities.wallet_balance import WalletBalance
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.interfaces.market_metadata_provider import (
    MarketMetadataProvider,
)
from finbot.core.domain.services.bot_manager.bot_manager_lock import (
    BotManagerLock,
)
from finbot.core.domain.services.bot_manager.bot_manager_state import (
    BotManagerState,
)

logger = logging.getLogger(__name__)


class SymbolSessionService:
    """Manage the active trading symbol and read exchange state for it."""

    def __init__(
        self,
        state: BotManagerState,
        lock: BotManagerLock,
        exchange: ExchangeGateway | None,
        metadata_provider: MarketMetadataProvider | None,
        repo: BotStateRepository,
    ) -> None:
        self._state = state
        self._lock = lock
        self._exchange = exchange
        self._metadata_provider = metadata_provider
        self._repo = repo

    @property
    def has_exchange(self) -> bool:
        """Return True if an exchange gateway is wired."""
        return self._exchange is not None

    def get_active_symbol(self) -> ActiveSymbolState | None:
        """Return the active symbol state, or None if fully idle."""
        with self._lock:
            return self._state.active_symbol

    def activate_symbol(self, symbol: str) -> dict[str, str]:
        """Activate a trading symbol, reading leverage from the exchange."""
        with self._lock:
            if self._state.runtime is not None:
                return {
                    "status": "rejected",
                    "message": "A strategy is running. Stop it first (/stop).",
                }
            previous = (
                self._state.active_symbol.symbol if self._state.active_symbol else None
            )
            leverage, margin_mode = self._read_exchange_leverage(symbol)
            self._state.active_symbol = ActiveSymbolState(
                symbol=symbol, leverage=leverage, margin_mode=margin_mode
            )
            self._persist_active_symbol()
        warning = self._switch_position_warning(previous, symbol)
        result: dict[str, str] = {
            "status": "active",
            "symbol": symbol,
            "leverage": str(leverage),
            "margin_mode": margin_mode,
        }
        if warning:
            result["warning"] = warning
        return result

    def get_active_price(self) -> Decimal | None:
        """Return the current price for the active symbol, or None if idle."""
        with self._lock:
            if self._state.active_symbol is None or self._exchange is None:
                return None
            symbol = self._state.active_symbol.symbol
        return self._exchange.get_price(symbol)

    def get_active_position(self) -> Any:
        """Return the exchange position for the active symbol, or None if idle."""
        with self._lock:
            if self._state.active_symbol is None or self._exchange is None:
                return None
            symbol = self._state.active_symbol.symbol
        return self._exchange.get_position(symbol)

    def list_active_orders(self) -> list[dict[str, Any]] | None:
        """Return open orders for the active symbol, or None if idle."""
        with self._lock:
            if self._state.active_symbol is None or self._exchange is None:
                return None
            symbol = self._state.active_symbol.symbol
        return self._exchange.list_open_orders(symbol)

    def get_balance(self) -> WalletBalance | None:
        """Return the wallet balance, or None if no exchange is wired."""
        if self._exchange is None:
            return None
        return self._exchange.get_balance()

    def set_leverage(
        self, leverage: int, margin_mode: str = "isolated"
    ) -> dict[str, str]:
        """Set leverage on the active symbol, validating against its max."""
        with self._lock:
            if self._state.active_symbol is None:
                return {
                    "status": "rejected",
                    "message": "No active symbol. Use /symbol first.",
                }
            if leverage < 1:
                return {"status": "rejected", "message": "Leverage must be >= 1."}
            symbol = self._state.active_symbol.symbol
            max_lev = self._symbol_max_leverage(symbol)
            if max_lev and leverage > max_lev:
                return {
                    "status": "rejected",
                    "message": f"{symbol} max leverage is {max_lev}x.",
                }
        try:
            self._exchange.set_leverage(symbol, leverage, margin_mode)  # type: ignore[union-attr]
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        with self._lock:
            if self._state.active_symbol is not None:
                self._state.active_symbol = ActiveSymbolState(
                    symbol=symbol, leverage=leverage, margin_mode=margin_mode
                )
                self._persist_active_symbol()
        return {
            "status": "ok",
            "symbol": symbol,
            "leverage": str(leverage),
            "margin_mode": margin_mode,
        }

    # -- internal -----------------------------------------------------------

    def _read_exchange_leverage(self, symbol: str) -> tuple[int, str]:
        if self._exchange is None:
            return 1, "isolated"
        try:
            reported = self._exchange.get_leverage(symbol)
        except Exception:
            reported = None
        if reported is None:
            return 1, "isolated"
        return reported

    def _switch_position_warning(
        self, previous: str | None, new_symbol: str
    ) -> str | None:
        if (
            previous is None
            or previous.upper() == new_symbol.upper()
            or self._exchange is None
        ):
            return None
        try:
            pos = self._exchange.get_position(previous)
        except Exception:
            return None
        if pos is not None and pos.direction.value != "flat":
            return (
                f"Open position on {previous} ({pos.direction.value} {pos.size}). "
                f"Switching to {new_symbol} \u2014 close it with /close {previous}."
            )
        return None

    def _symbol_max_leverage(self, symbol: str) -> int:
        if self._metadata_provider is None:
            return 0
        try:
            meta = self._metadata_provider.get_metadata(symbol)
        except Exception:
            return 0
        return int(getattr(meta, "max_leverage", 0)) if meta else 0

    def _persist_active_symbol(self) -> None:
        try:
            if self._state.active_symbol is not None:
                self._repo.save_active_symbol(self._state.active_symbol)
        except Exception:
            logger.warning("Could not persist active symbol state")
