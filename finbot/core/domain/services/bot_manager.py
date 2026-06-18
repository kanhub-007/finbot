"""Manages a single bot instance lifecycle with thread-safe state.

The BotManager is a domain service: it depends only on domain interfaces
and the stdlib.  The concrete ``LiveTradingRuntimeUseCase`` is injected
via a factory callable so BotManager stays unaware of how the runtime is
constructed (composition root handles that).
"""

from __future__ import annotations

import logging
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from finbot.core.domain.dto.run_counts import RunCounts
from finbot.core.domain.entities.active_symbol_state import ActiveSymbolState
from finbot.core.domain.entities.audit_log_entry import AuditLogEntry
from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.order_response_record import (
    OrderResponseRecord,
)
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.core.domain.entities.risk_event_record import RiskEventRecord
from finbot.core.domain.entities.runtime_bot_config import RuntimeBotConfig
from finbot.core.domain.entities.strategy_execution_config import (
    StrategyExecutionConfig,
)
from finbot.core.domain.entities.wallet_balance import WalletBalance
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.services.bot_live_state import BotLiveState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols for dependency injection (domain-safe — no framework imports)
# ---------------------------------------------------------------------------


class RuntimeFactory(Protocol):
    """Callable that creates a trading runtime use case."""

    def __call__(
        self,
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        live_data: bool = True,
        warmup_bars: int = 100,
    ) -> Any: ...


class LiveStateAware(Protocol):
    """A runtime that accepts a BotLiveState for status updates."""

    def set_live_state(self, state: BotLiveState) -> None: ...


class BotConfigFactory(Protocol):
    """Callable that creates a BotConfig from settings (wired by startup)."""

    def __call__(self, settings: Any) -> Any: ...


class ExchangeCancel(Protocol):
    """Minimal exchange interface for panic cancellation."""

    def cancel_all(self, symbol: str) -> dict[str, object]: ...

    def get_position(self, symbol: str) -> Any: ...

    def submit_order(self, intent: Any) -> dict[str, object]: ...


# ---------------------------------------------------------------------------
# BotManager
# ---------------------------------------------------------------------------


class BotManager:
    """Owns the lifecycle of a single bot runtime instance.

    Only one bot can run at a time.  ``start()`` spawns a daemon
    thread for the runtime; ``stop()`` signals the runtime and joins
    the thread.  ``get_status()`` is safe to call from any thread.

    Public query methods (``list_bot_runs``, ``get_signals_for_run``,
    etc.) delegate to the injected repository so MCP tools never
    access internal attributes directly.
    """

    def __init__(
        self,
        *,
        runtime_factory: RuntimeFactory,
        repository: BotStateRepository,
        exchange: ExchangeCancel | None = None,
        settings: Any | None = None,
        create_bot_config: BotConfigFactory | None = None,
        startup_time: float | None = None,
        metadata_provider: Any | None = None,
    ) -> None:
        self._runtime_factory = runtime_factory
        self._repo = repository
        self._exchange = exchange
        self._settings = settings
        self._create_bot_config = create_bot_config
        self._startup_time = startup_time or time.time()
        self._metadata_provider = metadata_provider
        self._state = BotLiveState()
        self._runtime: Any | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # Active symbol state (None = fully idle). See trading-control spec.
        # Restored from the repository so leverage survives restarts.
        self._active_symbol: ActiveSymbolState | None = (
            self._restore_active_symbol()
        )
        # Mutable runtime config shared by strategy + manual gates.
        # Seeded from settings (.env defaults) when available.
        self._runtime_config = self._seed_runtime_config(settings)
        # Default order size for /long /short without explicit size (Slice 2).
        self._default_size: Decimal | None = None

    @staticmethod
    def _seed_runtime_config(settings: Any) -> RuntimeBotConfig:
        """Build a RuntimeBotConfig from settings (.env defaults)."""
        cfg = RuntimeBotConfig()
        if settings is None:
            return cfg
        for key in RuntimeBotConfig.AVAILABLE_KEYS:
            attr_map = {
                "max_position": "max_position_usd",
                "daily_loss": "max_daily_loss_usd",
                "max_orders": "max_open_orders",
                "stale_data": "stale_data_seconds",
            }
            attr = attr_map.get(key)
            if attr is None:
                continue
            val = getattr(settings, attr, None)
            if val is not None:
                try:
                    cfg.set(key, str(val))
                except (KeyError, ValueError):
                    pass
        return cfg

    def _restore_active_symbol(self) -> ActiveSymbolState | None:
        """Load persisted active symbol on startup (best-effort)."""
        try:
            return self._repo.load_active_symbol()
        except Exception:
            logger.warning("Could not restore active symbol state")
            return None

    # -- public lifecycle ----------------------------------------------------

    def start(
        self,
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        warmup_bars: int = 100,
        live_trading_ack: bool = False,
        execution_config: StrategyExecutionConfig | None = None,
    ) -> dict[str, str]:
        """Start a bot in a background thread.

        When ``execution_config`` is supplied (parsed from the strategy's
        optional ``execution`` block), leverage is synced to the exchange
        before the runtime starts.

        Returns a dict with ``status`` ("running" or "rejected") and
        ``bot_run_id`` (set on success) or ``message`` (on rejection).
        """
        # Sync leverage from strategy execution block (Slice 2). Done OUTSIDE
        # the lock because set_leverage acquires it and Lock is non-reentrant.
        if execution_config is not None:
            lev_result = self.set_leverage(
                execution_config.leverage,
                execution_config.margin_mode,
            )
            if lev_result.get("status") == "rejected":
                return lev_result

        with self._lock:
            error = self._guard_no_conflict()
            if error:
                return error

            error = self._validate_start_inputs(strategy_path, mode)
            if error:
                return error

            runtime, error = self._construct_runtime(
                strategy_path, symbol, interval, mode, warmup_bars
            )
            if error:
                return error

            bot_run_id, error = self._start_session(
                runtime, strategy_path, symbol, interval, mode, live_trading_ack
            )
            if error:
                return error

            self._activate_runtime(
                runtime, strategy_path, symbol, interval, mode, bot_run_id
            )
            return {"status": "running", "bot_run_id": bot_run_id}

    def stop(self) -> dict[str, str]:
        """Stop the running bot and join its thread.

        Safe to call when no bot is running — returns
        ``{"status": "no_bot_running"}``.
        """
        runtime: Any | None = None
        with self._lock:
            if self._runtime is None:
                return {"status": "no_bot_running", "bot_run_id": ""}
            runtime = self._runtime
            self._runtime = None
            self._state.update(running=False)

        runtime.stop()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

        return {"status": "stopped", "bot_run_id": self._state.bot_run_id}

    def get_status(self) -> dict[str, object]:
        """Return a live status snapshot.

        When no bot is running, includes ``last_run`` with the most
        recently completed ``BotRun`` summary (or ``None`` if there
        is no history).
        """
        with self._lock:
            is_running = self._runtime is not None

        status = self._state.snapshot()
        status["is_running"] = is_running
        status["uptime_seconds"] = time.time() - self._startup_time

        status["total_signals"] = max(
            int(status.get("total_signals", 0)), self._repo.count_signals()
        )
        status["total_orders"] = max(
            int(status.get("total_orders", 0)), self._repo.count_orders()
        )
        status["total_fills"] = max(
            int(status.get("total_fills", 0)), self._repo.count_fills()
        )

        if not is_running:
            last_run = self._repo.get_latest_bot_run()
            if last_run:
                status["last_run"] = _serialize_bot_run(last_run)
            else:
                status["last_run"] = None

        return status

    def is_running(self) -> bool:
        """Return True if a bot is currently running."""
        with self._lock:
            return self._runtime is not None

    def get_active_symbol(self) -> ActiveSymbolState | None:
        """Return the active symbol state, or None if the bot is fully idle.

        On startup this is None. ``/symbol`` sets it; ``/symbol clear`` or a
        switch replaces it. The exchange is the source of truth for positions,
        but leverage/margin live here so they survive restarts.
        """
        with self._lock:
            return self._active_symbol

    def activate_symbol(self, symbol: str) -> dict[str, str]:
        """Activate a trading symbol, reading leverage from the exchange.

        Per the trading-control spec: this does NOT call set_leverage. It
        reads the current exchange leverage (falling back to 1x isolated if
        unavailable) and stores it in :class:`ActiveSymbolState`.

        Returns a dict with ``status`` ("active" or "rejected") and either
        ``symbol``/``leverage``/``margin_mode`` or ``message``.
        """
        with self._lock:
            if self._runtime is not None:
                return {
                    "status": "rejected",
                    "message": "A strategy is running. Stop it first (/stop).",
                }

            leverage, margin_mode = self._read_exchange_leverage(symbol)
            self._active_symbol = ActiveSymbolState(
                symbol=symbol,
                leverage=leverage,
                margin_mode=margin_mode,
            )
            self._persist_active_symbol()
            return {
                "status": "active",
                "symbol": symbol,
                "leverage": str(leverage),
                "margin_mode": margin_mode,
            }

    def _read_exchange_leverage(self, symbol: str) -> tuple[int, str]:
        """Read leverage from the exchange, falling back to 1x isolated."""
        if self._exchange is None:
            return 1, "isolated"
        try:
            reported = self._exchange.get_leverage(symbol)
        except Exception:
            reported = None
        if reported is None:
            return 1, "isolated"
        return reported

    def get_active_price(self) -> Decimal | None:
        """Return the current price for the active symbol, or None if idle.

        Returns None when no symbol is active so callers can surface a clear
        "select a symbol first" message.
        """
        with self._lock:
            if self._active_symbol is None or self._exchange is None:
                return None
            symbol = self._active_symbol.symbol
        return self._exchange.get_price(symbol)

    def get_active_position(self):
        """Return the exchange position for the active symbol, or None if idle.

        The exchange is the source of truth for positions (see Restart
        scenario). Returns a FLAT snapshot when the symbol has no position.
        """
        with self._lock:
            if self._active_symbol is None or self._exchange is None:
                return None
            symbol = self._active_symbol.symbol
        return self._exchange.get_position(symbol)

    def list_active_orders(self) -> list[dict[str, Any]] | None:
        """Return open orders for the active symbol, or None if idle.

        Returns an empty list when the symbol has no open orders. The
        exchange is the source of truth.
        """
        with self._lock:
            if self._active_symbol is None or self._exchange is None:
                return None
            symbol = self._active_symbol.symbol
        return self._exchange.list_open_orders(symbol)

    def get_balance(self) -> WalletBalance | None:
        """Return the wallet balance, or None if no exchange is wired."""
        if self._exchange is None:
            return None
        return self._exchange.get_balance()

    def get_bot_config(self) -> RuntimeBotConfig:
        """Return the mutable runtime config (shared with risk gates)."""
        return self._runtime_config

    def update_bot_config(self, key: str, value: str) -> dict[str, str]:
        """Update a runtime config key by short name (max_position, etc.)."""
        try:
            self._runtime_config.set(key, value)
        except KeyError:
            available = ", ".join(RuntimeBotConfig.AVAILABLE_KEYS)
            return {
                "status": "rejected",
                "message": f"Unknown setting. Available: {available}",
            }
        except ValueError as exc:
            return {"status": "rejected", "message": str(exc)}
        return {"status": "ok", "key": key, "value": value}

    def set_default_size(self, size) -> dict[str, str]:
        """Set the default order size for /long /short without explicit size."""
        size_dec = Decimal(str(size))
        if size_dec <= 0:
            return {"status": "rejected", "message": "Size must be positive."}
        with self._lock:
            self._default_size = size_dec
        return {"status": "ok", "default_size": str(size_dec)}

    def get_default_size(self) -> Decimal | None:
        """Return the default order size, or None if unset."""
        with self._lock:
            return self._default_size

    def clear_default_size(self) -> None:
        """Clear the default order size."""
        with self._lock:
            self._default_size = None

    def submit_manual_order(self, side, size) -> dict[str, Any]:
        """Submit a manual market order on the active symbol.

        Guards (trading-control spec): requires an active symbol, no running
        strategy, no open position, and passes the manual risk gates.
        Returns a dict with ``status`` ("ok"/"rejected"/"error") and either
        the order response or a ``message``.
        """
        from finbot.core.domain.entities.order_intent import OrderIntent
        from finbot.core.domain.entities.order_type import OrderType

        with self._lock:
            if self._active_symbol is None:
                return {
                    "status": "rejected",
                    "message": "No active symbol. Use /symbol first.",
                }
            if self._runtime is not None:
                return {
                    "status": "rejected",
                    "message": "A strategy is running. Stop it first (/stop).",
                }
            # Resolve size: explicit > default > rejected
            resolved = size if size is not None else self._default_size
            if resolved is None:
                return {
                    "status": "rejected",
                    "message": "No size given and no default set. Use /size first.",
                }
            if Decimal(str(resolved)) <= 0:
                return {
                    "status": "rejected",
                    "message": "Size must be positive.",
                }
            symbol = self._active_symbol.symbol

        # Position check (exchange is source of truth)
        position = self._exchange.get_position(symbol)
        if position.direction.value != "flat":
            return {
                "status": "rejected",
                "message": (
                    f"Position open on {symbol}. Close it first (/close)."
                ),
            }

        intent = OrderIntent(
            symbol=symbol,
            side=side,
            size=Decimal(str(resolved)),
            order_type=OrderType.MARKET,
            reduce_only=False,
        )

        # Risk gates
        price = self._safe_price(symbol)
        gate_error = self._run_manual_gates(intent, {"price": price})
        if gate_error is not None:
            return {"status": "rejected", "message": gate_error}

        try:
            response = self._exchange.submit_order(intent)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        return {"status": "ok", "response": response, "symbol": symbol}

    def _safe_price(self, symbol: str) -> Decimal | None:
        """Best-effort current price; None if unavailable."""
        try:
            return self._exchange.get_price(symbol)
        except Exception:
            return None

    def _run_manual_gates(
        self, intent, context: dict[str, Any]
    ) -> str | None:
        """Run the manual gate chain; return the first rejection reason or None."""
        from finbot.core.domain.services.risk_gates.manual_max_position_gate import (
            ManualMaxPositionGate,
        )
        from finbot.core.domain.services.risk_gates.manual_mode_gate import (
            ManualModeGate,
        )

        mode = getattr(self._settings, "mode", "dry_run") if self._settings else "dry_run"
        ack = (
            getattr(self._settings, "live_trading_ack", False)
            if self._settings
            else False
        )
        gates = [
            ManualModeGate(mode=mode, live_trading_ack=ack),
            ManualMaxPositionGate(self._runtime_config),
        ]
        for gate in gates:
            decision = gate.check(intent, context)
            if not decision.accepted:
                return decision.reason
        return None

    def set_leverage(
        self, leverage: int, margin_mode: str = "isolated"
    ) -> dict[str, str]:
        """Set leverage on the active symbol, validating against its max.

        Per the trading-control spec: validates ``1 <= leverage <= max_leverage``
        (when metadata is available), then calls the exchange and updates
        :class:`ActiveSymbolState`. Surface exchange errors verbatim.
        """
        with self._lock:
            if self._active_symbol is None:
                return {
                    "status": "rejected",
                    "message": "No active symbol. Use /symbol first.",
                }
            if leverage < 1:
                return {
                    "status": "rejected",
                    "message": f"Leverage must be >= 1.",
                }

            symbol = self._active_symbol.symbol
            max_lev = self._symbol_max_leverage(symbol)
            if max_lev and leverage > max_lev:
                return {
                    "status": "rejected",
                    "message": f"{symbol} max leverage is {max_lev}x.",
                }

        # Call exchange outside the lock (network I/O).
        try:
            self._exchange.set_leverage(symbol, leverage, margin_mode)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

        with self._lock:
            if self._active_symbol is not None:
                self._active_symbol = ActiveSymbolState(
                    symbol=symbol,
                    leverage=leverage,
                    margin_mode=margin_mode,
                )
                self._persist_active_symbol()
        return {
            "status": "ok",
            "symbol": symbol,
            "leverage": str(leverage),
            "margin_mode": margin_mode,
        }

    def _symbol_max_leverage(self, symbol: str) -> int:
        """Return max leverage for a symbol, or 0 if unknown."""
        if self._metadata_provider is None:
            return 0
        try:
            meta = self._metadata_provider.get_metadata(symbol)
        except Exception:
            return 0
        return int(getattr(meta, "max_leverage", 0)) if meta else 0

    @staticmethod
    def _resolve_risk_price(
        price, entry: Decimal, kind: str, is_long: bool
    ) -> Decimal:
        """Resolve an SL/TP price from absolute or percentage input.

        ``"2%"`` is interpreted relative to entry:
          - SL on long: entry * (1 - pct/100)  (below entry)
          - SL on short: entry * (1 + pct/100) (above entry)
          - TP on long: entry * (1 + pct/100)  (above entry)
          - TP on short: entry * (1 - pct/100) (below entry)

        Absolute prices (``94000``, ``Decimal('94000')``) are used as-is.
        """
        price_str = str(price).strip()
        if price_str.endswith("%"):
            pct = Decimal(price_str[:-1])
            if kind == "SL":
                factor = Decimal("1") - (pct / Decimal("100")) if is_long else Decimal("1") + (pct / Decimal("100"))
            else:  # TP
                factor = Decimal("1") + (pct / Decimal("100")) if is_long else Decimal("1") - (pct / Decimal("100"))
            return entry * factor
        return Decimal(price_str)

    def _persist_active_symbol(self) -> None:
        """Best-effort persist of the active symbol state."""
        try:
            if self._active_symbol is not None:
                self._repo.save_active_symbol(self._active_symbol)
        except Exception:
            logger.warning("Could not persist active symbol state")

    # -- public query methods (delegate to repo/exchange) --------------------

    # Implementation note (CQRS-lite): these read-only query methods
    # delegate directly to the repository.  MCP tools call these instead
    # of accessing ``_repo`` / ``_exchange`` directly, keeping the
    # presentation layer decoupled from BotManager internals.

    def get_bot_run(self, run_id: str) -> BotRun | None:
        """Return a single bot run by ID, or None."""
        return self._repo.get_bot_run(run_id)

    def list_bot_runs(
        self, limit: int = 20, mode_filter: str | None = None
    ) -> list[BotRun]:
        """Return recent bot runs ordered by most recent first."""
        return self._repo.list_bot_runs(limit=limit, mode_filter=mode_filter)

    def get_signals_for_run(self, run_id: str) -> list[ProcessedSignal]:
        """Return all signals for a specific bot run."""
        return self._repo.get_signals_for_run(run_id)

    def get_orders_for_run(self, run_id: str) -> list[OrderResponseRecord]:
        """Return all order responses for a specific bot run."""
        return self._repo.get_orders_for_run(run_id)

    def get_fills_for_run(self, run_id: str) -> list[FillRecord]:
        """Return all fills for a specific bot run."""
        return self._repo.get_fills_for_run(run_id)

    def get_run_counts(self, run_ids: list[str]) -> dict[str, RunCounts]:
        """Return signal/order/fill counts for many runs in one batch.

        Used by list endpoints to avoid an N+1 query per run.
        """
        return self._repo.get_run_counts(run_ids)

    def get_risk_events_for_run(self, run_id: str) -> list[RiskEventRecord]:
        """Return all risk events for a specific bot run."""
        return self._repo.get_risk_events_for_run(run_id)

    def get_audit_log(
        self, limit: int = 50, event_type: str | None = None
    ) -> list[AuditLogEntry]:
        """Return recent audit log entries."""
        return self._repo.get_audit_log(limit=limit, event_type=event_type)

    def cancel_all_orders(self, symbol: str) -> dict[str, object]:
        """Cancel all open orders for a symbol via the exchange.

        Returns an error dict if no exchange is wired.
        """
        if self._exchange is None:
            return {"error": "No exchange gateway wired"}
        return self._exchange.cancel_all(symbol)

    def close_position(self, symbol: str) -> dict[str, object]:
        """Market-close the position for a symbol via the exchange.

        Returns an info dict if no position is open or no exchange is wired.
        """
        if self._exchange is None:
            return {"error": "No exchange gateway wired"}

        result = self._close_symbol_position(symbol)
        if result.get("status") != "ok":
            return result
        # Cancel attached SL/TP trigger orders (cloid scheme).
        self._clear_risk_orders(symbol)
        return result

    def close_active_position(self) -> dict[str, str]:
        """Reduce-only market close on the active symbol; clears SL/TP.

        Per the trading-control spec: /close uses the active symbol. Allowed
        even while a strategy runs (emergency exit) but warns.
        """
        with self._lock:
            if self._active_symbol is None:
                return {
                    "status": "rejected",
                    "message": "No active symbol. Use /symbol first.",
                }
            symbol = self._active_symbol.symbol
            strategy_running = self._runtime is not None

        if self._exchange is None:
            return {"status": "error", "message": "No exchange gateway wired"}

        result = self._close_symbol_position(symbol)
        if result.get("status") == "ok":
            self._clear_risk_orders(symbol)
            if strategy_running:
                result["warning"] = (
                    "Strategy running — this may conflict. Consider /stop first."
                )
        return result

    def _close_symbol_position(self, symbol: str) -> dict[str, object]:
        """Submit a reduce-only market close for a symbol's full position."""
        from finbot.core.domain.entities.order_intent import OrderIntent
        from finbot.core.domain.entities.order_side import OrderSide
        from finbot.core.domain.entities.order_type import OrderType
        from finbot.core.domain.entities.position_direction import (
            PositionDirection,
        )

        pos = self._exchange.get_position(symbol)
        if pos is None or pos.direction.value == "flat":
            return {
                "status": "rejected",
                "message": f"No open position on {symbol}.",
            }

        side = (
            OrderSide.SELL if pos.direction == PositionDirection.LONG else OrderSide.BUY
        )
        intent = OrderIntent(
            symbol=symbol,
            side=side,
            size=pos.size,
            order_type=OrderType.MARKET,
            reduce_only=True,
        )
        response = self._exchange.submit_order(intent)
        return {"status": "ok", "response": response, "symbol": symbol}

    def _clear_risk_orders(self, symbol: str) -> None:
        """Cancel SL/TP trigger orders for a symbol (cloid scheme).

        No-op until /sl and /tp are implemented; failures are logged, not
        raised, so a position close never fails due to cleanup.
        """
        for prefix in ("SL:", "TP:"):
            cloid = f"{prefix}{symbol}"
            try:
                self._exchange.cancel_by_cloid(symbol, cloid)
            except Exception:
                logger.warning("Failed to cancel risk order %s", cloid)

    def clear_all(self) -> dict[str, Any]:
        """Cancel all orders and close all positions on the active symbol.

        Per the trading-control spec: requires no running strategy (hard
        block — use /panic for emergency stop+clear). Clears the active
        symbol's orders, SL/TP triggers, and position.

        Note: multi-symbol clear is deferred to portfolio support (Slice 3).
        """
        with self._lock:
            if self._runtime is not None:
                return {
                    "status": "rejected",
                    "message": (
                        "A strategy is running. Stop it first (/stop). "
                        "Use /panic for emergency stop+clear."
                    ),
                }
            if self._active_symbol is None:
                return {
                    "status": "rejected",
                    "message": "No active symbol to clear.",
                }
            symbol = self._active_symbol.symbol

        if self._exchange is None:
            return {"status": "error", "message": "No exchange gateway wired"}

        # Cancel all open orders on the symbol
        cancel_result = self._exchange.cancel_all(symbol)
        cancelled = (
            cancel_result.get("cancelled", 0) if isinstance(cancel_result, dict) else 0
        )

        # Clear SL/TP trigger orders
        self._clear_risk_orders(symbol)

        # Close any open position
        pos = self._exchange.get_position(symbol)
        closed = 0
        if pos is not None and pos.direction.value != "flat":
            close_result = self._close_symbol_position(symbol)
            if close_result.get("status") == "ok":
                closed = 1

        if cancelled == 0 and closed == 0:
            return {
                "status": "rejected",
                "message": "Nothing to clear.",
            }
        return {
            "status": "ok",
            "symbol": symbol,
            "cancelled_orders": cancelled,
            "closed_positions": closed,
        }

    def attach_stop_loss(self, price) -> dict[str, Any]:
        """Attach a reduce-only stop-loss trigger (cloid SL:<symbol>).

        Validates the price is on the correct side of entry (below for long,
        above for short). Replaces any existing SL for the symbol.
        """
        return self._attach_risk_order("SL", price)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel a single order on the active symbol by exchange oid.

        Different from /clear (all orders) and /sl clear (cloid-prefixed
        trigger). Returns ok/error from the exchange.
        """
        with self._lock:
            if self._active_symbol is None:
                return {
                    "status": "rejected",
                    "message": "No active symbol. Use /symbol first.",
                }
            if self._exchange is None:
                return {"status": "error", "message": "No exchange wired"}
            symbol = self._active_symbol.symbol
        try:
            result = self._exchange.cancel_by_oid(symbol, order_id)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        if isinstance(result, dict) and result.get("status") not in (
            "ok",
            "success",
            None,
        ):
            return {
                "status": "error",
                "message": str(result.get("message", "unknown")),
            }
        return {"status": "ok", "order_id": order_id, "symbol": symbol}

    def attach_take_profit(self, price) -> dict[str, Any]:
        """Attach a reduce-only take-profit trigger (cloid TP:<symbol>).

        Validates the price is on the correct side of entry (above for long,
        below for short). Replaces any existing TP for the symbol.
        """
        return self._attach_risk_order("TP", price)

    def clear_risk_order(self, kind: str) -> dict[str, Any]:
        """Cancel an SL or TP trigger order by kind ('sl' or 'tp')."""
        prefix = {"sl": "SL:", "tp": "TP:"}.get(kind.lower())
        if prefix is None:
            return {"status": "rejected", "message": f"Unknown kind: {kind}"}
        with self._lock:
            if self._active_symbol is None:
                return {
                    "status": "rejected",
                    "message": "No active symbol.",
                }
            symbol = self._active_symbol.symbol
        cloid = f"{prefix}{symbol}"
        try:
            self._exchange.cancel_by_cloid(symbol, cloid)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        return {"status": "ok", "kind": kind, "symbol": symbol}

    def _attach_risk_order(self, kind: str, price) -> dict[str, Any]:
        """Shared SL/TP attachment: validate, cancel existing, place new.

        ``kind`` is "SL" or "TP". Price-direction validation:
          - SL on a long must be below entry; on a short, above entry.
          - TP on a long must be above entry; on a short, below entry.
        """
        from finbot.core.domain.entities.order_intent import OrderIntent
        from finbot.core.domain.entities.order_side import OrderSide
        from finbot.core.domain.entities.order_type import OrderType
        from finbot.core.domain.entities.position_direction import (
            PositionDirection,
        )

        with self._lock:
            if self._active_symbol is None:
                return {
                    "status": "rejected",
                    "message": "No active symbol. Use /symbol first.",
                }
            if self._runtime is not None:
                return {
                    "status": "rejected",
                    "message": "A strategy is running. Stop it first (/stop).",
                }
            symbol = self._active_symbol.symbol

        pos = self._exchange.get_position(symbol)
        if pos is None or pos.direction.value == "flat":
            return {
                "status": "rejected",
                "message": f"No open position on {symbol} to protect.",
            }

        entry = pos.entry_price or Decimal("0")
        is_long = pos.direction == PositionDirection.LONG
        price_dec = self._resolve_risk_price(price, entry, kind, is_long)

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
            side = OrderSide.SELL if is_long else OrderSide.BUY
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

        # Replace existing (cancel old cloid first)
        cloid = f"{kind}:{symbol}"
        try:
            self._exchange.cancel_by_cloid(symbol, cloid)
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

    @property
    def has_exchange(self) -> bool:
        """Return True if an exchange gateway is wired."""
        return self._exchange is not None

    # -- internal ------------------------------------------------------------

    def _guard_no_conflict(self) -> dict[str, str] | None:
        if self._runtime is not None:
            return {
                "status": "rejected",
                "message": "Bot already running. Stop it first.",
            }
        return None

    @staticmethod
    def _validate_start_inputs(strategy_path: str, mode: str) -> dict[str, str] | None:
        if not Path(strategy_path).exists():
            return {
                "status": "rejected",
                "message": f"Strategy file not found: {strategy_path}",
            }
        if mode not in ("dry_run", "testnet", "live"):
            return {
                "status": "rejected",
                "message": f"Invalid mode: {mode}",
            }
        return None

    def _construct_runtime(
        self,
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        warmup_bars: int,
    ) -> tuple[Any | None, dict[str, str] | None]:
        try:
            runtime = self._runtime_factory(
                strategy_path=strategy_path,
                symbol=symbol,
                interval=interval,
                mode=mode,
                live_data=True,
                warmup_bars=warmup_bars,
            )
        except Exception as e:
            logger.exception("Failed to create runtime")
            return None, {
                "status": "rejected",
                "message": f"Failed to create runtime: {e}",
            }
        return runtime, None

    def _start_session(
        self,
        runtime: Any,
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        live_trading_ack: bool,
    ) -> tuple[str, dict[str, str] | None]:
        if mode in ("testnet", "live"):
            if self._create_bot_config is None:
                return "", {
                    "status": "rejected",
                    "message": "Config factory required for testnet/live mode.",
                }
            if self._settings is None:
                return "", {
                    "status": "rejected",
                    "message": "Settings required for testnet/live mode.",
                }
            config = self._create_bot_config(self._settings)
            result = runtime.start_live(strategy_path, symbol, interval, config)
            if result.status != "running":
                return "", {
                    "status": "rejected",
                    "message": result.message,
                }
            return result.message, None

        bot_run_id = runtime.start(strategy_path, symbol, interval)
        return bot_run_id, None

    def _activate_runtime(
        self,
        runtime: Any,
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        bot_run_id: str,
    ) -> None:
        self._runtime = runtime
        self._state.update(
            running=True,
            bot_run_id=bot_run_id,
            strategy_name=strategy_path,
            symbol=symbol,
            interval=interval,
            mode=mode,
            uptime_start=time.time(),
        )
        if hasattr(runtime, "set_live_state"):
            runtime.set_live_state(self._state)  # type: ignore[union-attr]

        self._thread = threading.Thread(
            target=self._run_forever,
            name="finbot-runtime",
            daemon=True,
        )
        self._thread.start()

    def _run_forever(self) -> None:
        """Target for the background runtime thread."""
        try:
            self._runtime.run_forever()  # type: ignore[union-attr]
        except Exception:
            logger.exception("Runtime thread crashed")
        finally:
            self._state.update(running=False)


# -- module-level helpers -----------------------------------------------------


def _serialize_bot_run(run: BotRun) -> dict[str, object]:
    """Convert a BotRun entity to a JSON-safe dict."""
    return {
        "run_id": run.run_id,
        "strategy_name": run.strategy_name,
        "symbol": run.symbol,
        "interval": run.interval,
        "mode": run.mode,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
    }
