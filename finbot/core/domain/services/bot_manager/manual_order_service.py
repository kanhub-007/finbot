"""ManualOrderService — manual orders, cancel, clear-all, close-position.

Handles interactive manual orders (/long, /short) separate from the
strategy signal pipeline. Guards: requires an active symbol, no running
strategy, no open position, and passes the manual risk gates.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.runtime_bot_config import RuntimeBotConfig
from finbot.core.domain.interfaces.bot_state_repository import BotStateRepository
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
from finbot.core.domain.services.bot_manager.recorded_order_submission import (
    submit_and_record,
)
from finbot.core.domain.services.bot_manager.risk_order_service import (
    RiskOrderService,
)

logger = logging.getLogger(__name__)


class ManualOrderService:
    """Submit manual market orders, cancel, clear, and close positions."""

    def __init__(
        self,
        state: BotManagerState,
        lock: BotManagerLock,
        exchange: ExchangeGateway | None,
        risk_orders: RiskOrderService,
        repository: BotStateRepository,
        metadata_provider: MarketMetadataProvider | None = None,
        mode: str = "dry_run",
        live_trading_ack: bool = False,
    ) -> None:
        self._state = state
        self._lock = lock
        self._exchange = exchange
        self._risk_orders = risk_orders
        self._repo = repository
        self._metadata_provider = metadata_provider
        self._mode = mode
        self._ack = live_trading_ack

    def set_metadata_provider(
        self, provider: MarketMetadataProvider | None
    ) -> None:
        """Replace the metadata provider (e.g. for test injection)."""
        self._metadata_provider = provider

    def submit_manual_order(
        self,
        side: OrderSide,
        size: Decimal | None,
        limit_px: Decimal | None = None,
        usd_notional: Decimal | None = None,
    ) -> dict[str, Any]:
        """Submit a manual market or limit order on the active symbol."""
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
            resolved = size if size is not None else self._state.default_size
            if resolved is None:
                return {
                    "status": "rejected",
                    "message": "No size given and no default set. Use /size first.",
                }
            if Decimal(str(resolved)) <= 0:
                return {"status": "rejected", "message": "Size must be positive."}
            size_error = _validate_size(
                self._metadata_provider, self._state.active_symbol, resolved
            )
            if size_error is not None:
                return {"status": "rejected", "message": size_error}
            symbol = self._state.active_symbol.symbol

        if self._exchange is None:
            return {"status": "error", "message": "No exchange gateway wired"}
        position = self._exchange.get_position(symbol)
        if position.direction.value != "flat":
            return {
                "status": "rejected",
                "message": f"Position open on {symbol}. Close it first (/close).",
            }

        intent = OrderIntent(
            symbol=symbol,
            side=side,
            size=Decimal(str(resolved)),
            order_type=OrderType.LIMIT if limit_px else OrderType.MARKET,
            reduce_only=False,
            limit_price=limit_px,
        )
        gate_error = _run_manual_gates(
            self._mode,
            self._ack,
            self._state.runtime_config,
            intent,
            {
                "price": _safe_price(self._exchange, symbol),
                "usd_notional": usd_notional,
            },
        )
        if gate_error is not None:
            return {"status": "rejected", "message": gate_error}
        return submit_and_record(
            self._exchange,
            self._repo,
            intent,
            symbol,
            cloid_prefix="manual",
        )

    def submit_manual_order_with_brackets(
        self,
        side: OrderSide,
        size: Decimal | None,
        sl_price: Decimal | None = None,
        tp_price: Decimal | None = None,
        limit_px: Decimal | None = None,
        usd_notional: Decimal | None = None,
    ) -> dict[str, Any]:
        """Submit a manual entry then attach SL/TP triggers in one call."""
        entry_result = self.submit_manual_order(
            side, size, limit_px=limit_px, usd_notional=usd_notional
        )
        if entry_result.get("status") != "ok":
            return entry_result
        symbol = entry_result.get("symbol", "")
        warnings: list[str] = []
        if sl_price is not None:
            sl_result = self._risk_orders.attach_stop_loss(sl_price)
            if sl_result.get("status") != "ok":
                warnings.append(
                    f"SL not attached: {sl_result.get('message', 'unknown')}"
                )
        if tp_price is not None:
            tp_result = self._risk_orders.attach_take_profit(tp_price)
            if tp_result.get("status") != "ok":
                warnings.append(
                    f"TP not attached: {tp_result.get('message', 'unknown')}"
                )
        result: dict[str, Any] = {
            "status": "ok",
            "symbol": symbol,
            "response": entry_result.get("response"),
        }
        if warnings:
            result["warnings"] = warnings
        return result

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel a single order on the active symbol by exchange oid."""
        with self._lock:
            if self._state.active_symbol is None:
                return {
                    "status": "rejected",
                    "message": "No active symbol. Use /symbol first.",
                }
            if self._exchange is None:
                return {"status": "error", "message": "No exchange wired"}
            symbol = self._state.active_symbol.symbol
        try:
            result = self._exchange.cancel_by_oid(symbol, order_id)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        if isinstance(result, dict) and result.get("status") not in (
            "ok",
            "success",
            None,
        ):
            return {"status": "error", "message": str(result.get("message", "unknown"))}
        return {"status": "ok", "order_id": order_id, "symbol": symbol}

    def cancel_all_orders(self, symbol: str) -> dict[str, object]:
        """Cancel all open orders for a symbol via the exchange."""
        if self._exchange is None:
            return {"error": "No exchange gateway wired"}
        return self._exchange.cancel_all(symbol)

    def close_position(self, symbol: str) -> dict[str, object]:
        """Market-close the position for a symbol; clears SL/TP."""
        if self._exchange is None:
            return {"error": "No exchange gateway wired"}
        result = _close_symbol_position(self._exchange, symbol, self._repo)
        if result.get("status") != "ok":
            return result
        self._risk_orders.clear_risk_orders_for_symbol(symbol)
        return result

    def close_active_position(self) -> dict[str, object]:
        """Reduce-only market close on the active symbol; clears SL/TP."""
        with self._lock:
            if self._state.active_symbol is None:
                return {
                    "status": "rejected",
                    "message": "No active symbol. Use /symbol first.",
                }
            symbol = self._state.active_symbol.symbol
            strategy_running = self._state.runtime is not None
        if self._exchange is None:
            return {"status": "error", "message": "No exchange gateway wired"}
        result = _close_symbol_position(self._exchange, symbol, self._repo)
        if result.get("status") == "ok":
            self._risk_orders.clear_risk_orders_for_symbol(symbol)
            if strategy_running:
                result["warning"] = (
                    "Strategy running — this may conflict. Consider /stop first."
                )
        return result

    def clear_all(self) -> dict[str, Any]:
        """Cancel all orders and close all positions on the active symbol."""
        with self._lock:
            if self._state.runtime is not None:
                return {
                    "status": "rejected",
                    "message": (
                        "A strategy is running. Stop it first (/stop). "
                        "Use /panic for emergency stop+clear."
                    ),
                }
            if self._state.active_symbol is None:
                return {"status": "rejected", "message": "No active symbol to clear."}
            symbol = self._state.active_symbol.symbol
        if self._exchange is None:
            return {"status": "error", "message": "No exchange gateway wired"}
        cancel_result = self._exchange.cancel_all(symbol)
        cancelled = (
            cancel_result.get("cancelled", 0) if isinstance(cancel_result, dict) else 0
        )
        self._risk_orders.clear_risk_orders_for_symbol(symbol)
        pos = self._exchange.get_position(symbol)
        closed = 0
        if pos is not None and pos.direction.value != "flat":
            if (
                _close_symbol_position(self._exchange, symbol, self._repo).get("status")
                == "ok"
            ):
                closed = 1
        if cancelled == 0 and closed == 0:
            return {"status": "rejected", "message": "Nothing to clear."}
        return {
            "status": "ok",
            "symbol": symbol,
            "cancelled_orders": cancelled,
            "closed_positions": closed,
        }


def _validate_size(metadata_provider, active_symbol, size) -> str | None:
    """Validate size precision (sz_decimals) and minimum (min_size)."""
    if metadata_provider is None or active_symbol is None:
        return None
    try:
        meta = metadata_provider.get_metadata(active_symbol.symbol)
    except Exception:
        return None
    if meta is None:
        return None
    size_dec = Decimal(str(size))
    sz_decimals = getattr(meta, "sz_decimals", 0) or 0
    min_size = getattr(meta, "min_size", Decimal("0")) or Decimal("0")
    size_str = format(size_dec.normalize(), "f")
    decimals = len(size_str.split(".")[1]) if "." in size_str else 0
    if decimals > sz_decimals:
        return f"Size too precise for {meta.symbol} (uses {sz_decimals} decimals)."
    if min_size > 0 and size_dec < min_size:
        return f"Size below minimum for {meta.symbol} (min {min_size})."
    return None


def _run_manual_gates(
    mode: str,
    ack: bool,
    config: RuntimeBotConfig,
    intent: OrderIntent,
    context: dict[str, Any],
) -> str | None:
    """Run the manual gate chain; return the first rejection reason or None."""
    from finbot.core.domain.services.risk_gates.registry import (
        build_default_manual_gates,
    )

    gates = build_default_manual_gates(mode=mode, live_trading_ack=ack, config=config)
    for gate in gates:
        decision = gate.check(intent, context)
        if not decision.accepted:
            return decision.reason
    return None


def _close_symbol_position(
    exchange: ExchangeGateway,
    symbol: str,
    repo: BotStateRepository,
) -> dict[str, object]:
    """Submit a reduce-only market close for a symbol's full position."""
    pos = exchange.get_position(symbol)
    if pos is None or pos.direction.value == "flat":
        return {"status": "rejected", "message": f"No open position on {symbol}."}
    side = OrderSide.SELL if pos.direction == PositionDirection.LONG else OrderSide.BUY
    intent = OrderIntent(
        symbol=symbol,
        side=side,
        size=pos.size,
        order_type=OrderType.MARKET,
        reduce_only=True,
    )
    return submit_and_record(exchange, repo, intent, symbol, cloid_prefix="manual")


def _safe_price(exchange: ExchangeGateway, symbol: str) -> Decimal | None:
    """Best-effort current price; None if unavailable."""
    try:
        return exchange.get_price(symbol)
    except Exception:
        return None
