"""BotManagerPort — domain protocols for bot lifecycle, trading control, config.

Split into role-specific protocols (F3 — Interface Segregation) so
callers can depend on only the methods they need.  ``BotManagerPort``
remains as the composite protocol for backward compatibility.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from finbot.core.domain.entities.order_side import OrderSide


class BotLifecycleOps(Protocol):
    """Start / stop / status operations."""

    def is_running(self) -> bool: ...

    def get_status(self) -> dict[str, object]: ...

    def start(
        self,
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        warmup_bars: int = 100,
        live_trading_ack: bool = False,
    ) -> dict[str, str]: ...

    def stop(self) -> dict[str, str]: ...


class BotQueryOps(Protocol):
    """Read-only history queries."""

    def list_bot_runs(
        self, limit: int = 20, mode_filter: str | None = None
    ) -> list[Any]: ...


class PanicOps(Protocol):
    """Emergency kill-switch operations."""

    def cancel_all_orders(self, symbol: str) -> dict[str, object]: ...

    def close_position(self, symbol: str) -> dict[str, object]: ...


class SymbolOps(Protocol):
    """Active-symbol management and exchange reads."""

    def activate_symbol(self, symbol: str) -> dict[str, str]: ...

    def get_active_symbol(self) -> Any: ...

    def get_active_price(self) -> Decimal | None: ...

    def get_active_position(self) -> Any: ...

    def get_balance(self) -> Any: ...

    def set_leverage(
        self, leverage: int, margin_mode: str = "isolated"
    ) -> dict[str, str]: ...


class OrderOps(Protocol):
    """Manual order submission and cancellation."""

    def submit_manual_order(
        self, side: OrderSide, size: Decimal
    ) -> dict[str, Any]: ...

    def submit_manual_order_with_brackets(
        self,
        side: OrderSide,
        size: Decimal,
        sl_price: Decimal | None = None,
        tp_price: Decimal | None = None,
    ) -> dict[str, Any]: ...

    def close_active_position(self) -> dict[str, str]: ...

    def clear_all(self) -> dict[str, Any]: ...

    def list_active_orders(self) -> list[dict[str, Any]] | None: ...

    def cancel_order(self, order_id: str) -> dict[str, Any]: ...


class RiskOrderOps(Protocol):
    """SL/TP trigger order management."""

    def attach_stop_loss(self, price: Decimal | str) -> dict[str, Any]: ...

    def attach_take_profit(self, price: Decimal | str) -> dict[str, Any]: ...

    def clear_risk_order(self, kind: str) -> dict[str, Any]: ...


class ConfigOps(Protocol):
    """Runtime configuration management."""

    def save_config_profile(self, name: str) -> dict[str, Any]: ...

    def load_config_profile(self, name: str) -> dict[str, Any]: ...

    def list_config_profiles(self) -> dict[str, Any]: ...

    def get_bot_config(self) -> Any: ...

    def update_bot_config(self, key: str, value: str) -> dict[str, str]: ...

    def save_config_to_env(self) -> dict[str, str]: ...

    def set_default_size(self, size: Decimal) -> dict[str, str]: ...

    def get_default_size(self) -> Decimal | None: ...

    def clear_default_size(self) -> None: ...


class BotManagerPort(
    BotLifecycleOps,
    BotQueryOps,
    PanicOps,
    SymbolOps,
    OrderOps,
    RiskOrderOps,
    ConfigOps,
    Protocol,
):
    """Composite protocol — backward-compatible with all existing callers.

    New callers should depend on the smallest role-specific protocol they need.
    """
