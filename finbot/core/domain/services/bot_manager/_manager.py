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
from finbot.core.domain.services.bot_manager._trading_control import (
    TradingControlMixin,
)

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


class BotManager(TradingControlMixin):
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
        # Named config profiles (Slice 3). name -> snapshot dict.
        self._config_profiles: dict[str, Any] = {}

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
    # Trading-control methods are mixed in from TradingControlMixin.


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
