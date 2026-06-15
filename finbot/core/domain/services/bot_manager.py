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
from pathlib import Path
from typing import Any, Protocol

from finbot.core.domain.entities.audit_log_entry import AuditLogEntry
from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.order_response_record import (
    OrderResponseRecord,
)
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.core.domain.entities.risk_event_record import RiskEventRecord
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
    ) -> None:
        self._runtime_factory = runtime_factory
        self._repo = repository
        self._exchange = exchange
        self._settings = settings
        self._create_bot_config = create_bot_config
        self._startup_time = startup_time or time.time()
        self._state = BotLiveState()
        self._runtime: Any | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- public lifecycle ----------------------------------------------------

    def start(
        self,
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        warmup_bars: int = 100,
        live_trading_ack: bool = False,
    ) -> dict[str, str]:
        """Start a bot in a background thread.

        Returns a dict with ``status`` ("running" or "rejected") and
        ``bot_run_id`` (set on success) or ``message`` (on rejection).
        """
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

        pos = self._exchange.get_position(symbol)
        if pos is None or pos.direction.value == "flat":
            return {"message": "No open position to close"}

        from finbot.core.domain.entities.order_intent import OrderIntent
        from finbot.core.domain.entities.order_side import OrderSide
        from finbot.core.domain.entities.order_type import OrderType
        from finbot.core.domain.entities.position_direction import (
            PositionDirection,
        )

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
        return self._exchange.submit_order(intent)

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
