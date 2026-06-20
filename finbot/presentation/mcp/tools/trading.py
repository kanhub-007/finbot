"""MCP tools — manual trading control (queries + orders)."""

import json
from decimal import Decimal
from typing import Any

from fastmcp import FastMCP


def register_trading_tools(mcp: FastMCP, bot_manager: Any) -> None:
    """Register trading-query and manual-order MCP tools."""
    _register_trading_queries(mcp, bot_manager)
    _register_manual_orders(mcp, bot_manager)


def _register_trading_queries(mcp: FastMCP, bot_manager: Any) -> None:
    """Register read-only trading tools (symbol, price, balance, etc.)."""

    # -- queries -----------------------------------------------------------

    @mcp.tool(
        name="get_active_symbol",
        description=(
            "Get the currently active trading symbol and its leverage / "
            "margin mode. Use activate_symbol first to select a symbol."
        ),
    )
    def get_active_symbol() -> str:
        active = bot_manager.get_active_symbol()
        if active is None:
            return json.dumps({"status": "idle", "message": "No active symbol"})
        return json.dumps(
            {
                "symbol": active.symbol,
                "leverage": active.leverage,
                "margin_mode": active.margin_mode,
            },
            indent=2,
        )

    @mcp.tool(
        name="activate_symbol",
        description=(
            "Activate a trading symbol. Reads current leverage from the "
            "exchange without overwriting it. Required before placing "
            "orders or checking positions."
        ),
    )
    def activate_symbol(symbol: str) -> str:
        result = bot_manager.activate_symbol(symbol)
        return json.dumps(result, indent=2)

    @mcp.tool(
        name="get_price",
        description="Get the current mark/mid price for the active symbol.",
    )
    def get_price() -> str:
        price = bot_manager.get_active_price()
        if price is None:
            return json.dumps({"status": "error", "message": "No active symbol"})
        return json.dumps({"price": str(price)}, indent=2)

    @mcp.tool(
        name="get_balance",
        description=(
            "Get the current account balance: perp margin value, margin "
            "used, available (withdrawable), and spot USDC balance."
        ),
    )
    def get_balance() -> str:
        bal = bot_manager.get_balance()
        if bal is None:
            return json.dumps({"status": "error", "message": "No exchange wired"})
        return json.dumps(
            {
                "wallet_value": str(bal.wallet_value),
                "margin_used": str(bal.margin_used),
                "available": str(bal.available),
                "spot_usdc": str(bal.spot_usdc),
            },
            indent=2,
        )

    @mcp.tool(
        name="set_leverage",
        description=(
            "Set leverage and margin mode on the active symbol. "
            "Example: set_leverage(5, 'cross') for 5x cross margin."
        ),
    )
    def set_leverage(leverage: int, margin_mode: str = "isolated") -> str:
        result = bot_manager.set_leverage(leverage, margin_mode)
        return json.dumps(result, indent=2)

    @mcp.tool(
        name="get_leverage",
        description=(
            "View the current leverage and margin mode for the active symbol."
        ),
    )
    def get_leverage() -> str:
        active = bot_manager.get_active_symbol()
        if active is None:
            return json.dumps({"status": "error", "message": "No active symbol"})
        return json.dumps(
            {
                "symbol": active.symbol,
                "leverage": active.leverage,
                "margin_mode": active.margin_mode,
            },
            indent=2,
        )

    @mcp.tool(
        name="get_position",
        description=(
            "Get the current position for the active symbol: direction, "
            "size, entry price."
        ),
    )
    def get_position() -> str:
        active = bot_manager.get_active_symbol()
        if active is None:
            return json.dumps({"status": "error", "message": "No active symbol"})
        pos = bot_manager.get_active_position()
        if pos is None or pos.direction.value == "flat":
            return json.dumps(
                {"symbol": active.symbol, "direction": "flat", "size": "0"},
                indent=2,
            )
        return json.dumps(
            {
                "symbol": active.symbol,
                "direction": pos.direction.value,
                "size": str(pos.size),
                "entry_price": (str(pos.entry_price) if pos.entry_price else None),
            },
            indent=2,
        )

    @mcp.tool(
        name="list_open_orders",
        description="List open orders for the active symbol.",
    )
    def list_open_orders() -> str:
        orders = bot_manager.list_active_orders()
        if orders is None:
            return json.dumps(
                {"status": "error", "message": "No active symbol"}, indent=2
            )
        return json.dumps(orders, indent=2, default=str)


def _register_manual_orders(mcp: FastMCP, bot_manager: Any) -> None:
    """Register manual order placement tools (long, short, close, etc.)."""

    # -- manual orders -----------------------------------------------------

    @mcp.tool(
        name="place_long_order",
        description=(
            "Open a long position on the active symbol. SIZE is a USD "
            "notional (before leverage) or a percentage like '25%'. "
            "It is automatically converted to token amount using the "
            "current price and active symbol's leverage — exactly like "
            "Telegram /long.  Examples: place_long_order('100') for $100 "
            "market long. place_long_order('100', limit_px=95000) for "
            "limit order. place_long_order('100', sl_price=94000) for "
            "market + stop-loss."
        ),
    )
    def place_long_order(
        size: str,
        limit_px: float | None = None,
        sl_price: float | None = None,
        tp_price: float | None = None,
    ) -> str:
        return _submit_usd_order(bot_manager, "buy", size, limit_px, sl_price, tp_price)

    @mcp.tool(
        name="place_short_order",
        description=(
            "Open a short position on the active symbol. Same behaviour "
            "as place_long_order. SIZE is USD notional (before leverage)."
        ),
    )
    def place_short_order(
        size: str,
        limit_px: float | None = None,
        sl_price: float | None = None,
        tp_price: float | None = None,
    ) -> str:
        return _submit_usd_order(
            bot_manager, "sell", size, limit_px, sl_price, tp_price
        )

    @mcp.tool(
        name="close_position",
        description=(
            "Market-close the active position (reduce-only). Also clears "
            "any attached SL/TP orders."
        ),
    )
    def close_position() -> str:
        result = bot_manager.close_active_position()
        return json.dumps(result, indent=2, default=str)

    @mcp.tool(
        name="set_stop_loss",
        description=(
            "Attach or update a stop-loss trigger order. PRICE can be "
            "absolute (e.g. 94000) or percentage (e.g. '2%'). "
            "Requires an open position on the active symbol."
        ),
    )
    def set_stop_loss(price: str) -> str:
        result = bot_manager.attach_stop_loss(price)
        return json.dumps(result, indent=2, default=str)

    @mcp.tool(
        name="set_take_profit",
        description=(
            "Attach or update a take-profit trigger order. PRICE can be "
            "absolute (e.g. 100000) or percentage (e.g. '3%'). "
            "Requires an open position on the active symbol."
        ),
    )
    def set_take_profit(price: str) -> str:
        result = bot_manager.attach_take_profit(price)
        return json.dumps(result, indent=2, default=str)

    @mcp.tool(
        name="cancel_order",
        description="Cancel a single order by exchange order ID (oid).",
    )
    def cancel_order(order_id: str) -> str:
        result = bot_manager.cancel_order(order_id)
        return json.dumps(result, indent=2, default=str)

    @mcp.tool(
        name="clear_all",
        description=(
            "Cancel all open orders and close all positions on the "
            "active symbol. Only works when no strategy is running."
        ),
    )
    def clear_all() -> str:
        result = bot_manager.clear_all()
        return json.dumps(result, indent=2, default=str)


# -- helpers ---------------------------------------------------------------


def _submit_usd_order(
    bot_manager: Any,
    side: str,
    size_raw: str,
    limit_px: float | None,
    sl_price: float | None,
    tp_price: float | None,
) -> str:
    """Convert USD size to token amount, then submit the manual order."""
    from finbot.core.domain.services.order_size_resolver import (
        resolve_order_size,
    )

    active = bot_manager.get_active_symbol()
    if active is None:
        return json.dumps(
            {
                "status": "rejected",
                "message": "No active symbol. Use activate_symbol first.",
            },
            indent=2,
        )

    price = bot_manager.get_active_price()
    if price is None or price <= 0:
        return json.dumps(
            {"status": "rejected", "message": "Price unavailable"},
            indent=2,
        )

    leverage = int(getattr(active, "leverage", 1) or 1)
    balance = None
    if size_raw.strip().endswith("%"):
        bal = bot_manager.get_balance()
        if bal is not None:
            balance = max(bal.available, Decimal("0")) + max(
                bal.spot_usdc, Decimal("0")
            )

    resolved = resolve_order_size(size_raw, price, leverage, available_balance=balance)
    if isinstance(resolved, str):
        return json.dumps({"status": "rejected", "message": resolved}, indent=2)

    sl_d = Decimal(str(sl_price)) if sl_price is not None else None
    tp_d = Decimal(str(tp_price)) if tp_price is not None else None
    limit_px_d = Decimal(str(limit_px)) if limit_px is not None else None

    if sl_d is not None or tp_d is not None:
        order_result = bot_manager.submit_manual_order_with_brackets(
            side,
            resolved.token_size,
            sl_price=sl_d,
            tp_price=tp_d,
            limit_px=limit_px_d,
            usd_notional=resolved.raw_usd,
        )
    else:
        order_result = bot_manager.submit_manual_order(
            side,
            resolved.token_size,
            limit_px=limit_px_d,
            usd_notional=resolved.raw_usd,
        )
    return json.dumps(order_result, indent=2, default=str)
