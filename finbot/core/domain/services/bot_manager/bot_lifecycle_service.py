"""BotLifecycleService — start/stop/get_status/is_running, runtime thread.

Owns the background runtime thread and the :class:`BotLiveState` snapshot.
``start`` does pre-flight checks (no conflict, valid inputs, no open
position on the symbol) then constructs the runtime via the injected
factory, starts its session, and spawns a daemon thread.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Protocol

from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.strategy_execution_config import (
    StrategyExecutionConfig,
)
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.services.bot_live_state import BotLiveState
from finbot.core.domain.services.bot_manager._protocols import (
    CreateBotConfigCallable,
    SettingsLike,
)
from finbot.core.domain.services.bot_manager.bot_manager_lock import (
    BotManagerLock,
)
from finbot.core.domain.services.bot_manager.bot_manager_state import (
    BotManagerState,
)

logger = logging.getLogger(__name__)


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


class BotLifecycleService:
    """Owns the lifecycle of a single bot runtime instance."""

    def __init__(
        self,
        state: BotManagerState,
        lock: BotManagerLock,
        repo: BotStateRepository,
        exchange: ExchangeGateway | None,
        runtime_factory: RuntimeFactory,
        settings: SettingsLike | None,
        create_bot_config: CreateBotConfigCallable | None,
        startup_time: float | None = None,
        live_state: BotLiveState | None = None,
        set_leverage_fn: object | None = None,
    ) -> None:
        self._state = state
        self._lock = lock
        self._repo = repo
        self._exchange = exchange
        self._runtime_factory = runtime_factory
        self._settings = settings
        self._create_bot_config = create_bot_config
        self._startup_time = startup_time or time.time()
        self._live_state = live_state or BotLiveState()
        self._set_leverage_fn = set_leverage_fn

    @property
    def live_state(self) -> BotLiveState:
        """The live status snapshot (written by the runtime thread)."""
        return self._live_state

    def is_running(self) -> bool:
        """Return True if a bot is currently running."""
        with self._lock:
            return self._state.runtime is not None

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
        """Start a bot in a background thread."""
        # Sync leverage outside the lock (set_leverage acquires it).
        if execution_config is not None and self._set_leverage_fn is not None:
            lev_result = self._set_leverage_fn(
                execution_config.leverage, execution_config.margin_mode
            )
            if lev_result.get("status") == "rejected":
                return lev_result
        if self._exchange is not None:
            try:
                pos = self._exchange.get_position(symbol)
                if pos is not None and pos.direction.value != "flat":
                    return {
                        "status": "rejected",
                        "message": (
                            f"Open position on {symbol}. " "Close it first (/close)."
                        ),
                    }
            except Exception:
                pass
        with self._lock:
            if self._state.runtime is not None:
                return {
                    "status": "rejected",
                    "message": "Bot already running. Stop it first.",
                }
            if mode not in ("dry_run", "testnet", "live"):
                return {"status": "rejected", "message": f"Invalid mode: {mode}"}
            runtime = self._construct_runtime(
                strategy_path, symbol, interval, mode, warmup_bars
            )
            if isinstance(runtime, dict):  # error
                return runtime
            bot_run_id = self._start_session(
                runtime, strategy_path, symbol, interval, mode
            )
            if isinstance(bot_run_id, dict):  # error
                return bot_run_id
            self._state.runtime = runtime
            self._live_state.update(
                running=True,
                bot_run_id=bot_run_id,
                strategy_name=strategy_path,
                symbol=symbol,
                interval=interval,
                mode=mode,
                uptime_start=time.time(),
            )
            if hasattr(runtime, "set_live_state"):
                runtime.set_live_state(self._live_state)
            self._state.thread = threading.Thread(
                target=self._run_forever, name="finbot-runtime", daemon=True
            )
            self._state.thread.start()
            result: dict[str, str] = {"status": "running", "bot_run_id": bot_run_id}
            # Include resolved timeframes via public API (MTF strategies override
            # the caller's interval via the YAML primary; informatives are
            # auto-discovered).  MCP / Telegram use this for display.
            if hasattr(runtime, "get_resolved_intervals"):
                resolved = runtime.get_resolved_intervals()
                result["interval"] = str(resolved.get("interval", ""))
                if "informative_intervals" in resolved:
                    result["informative_intervals"] = str(
                        resolved["informative_intervals"]
                    )
            return result

    def stop(self) -> dict[str, str]:
        """Stop the running bot and join its thread."""
        with self._lock:
            if self._state.runtime is None:
                return {"status": "no_bot_running", "bot_run_id": ""}
            runtime = self._state.runtime
            self._state.runtime = None
            self._live_state.update(running=False)
        runtime.stop()
        if self._state.thread is not None:
            self._state.thread.join(timeout=5.0)
            self._state.thread = None
        return {"status": "stopped", "bot_run_id": self._live_state.bot_run_id}

    def get_status(self) -> dict[str, object]:
        """Return a live status snapshot."""
        with self._lock:
            is_running = self._state.runtime is not None
        status = self._live_state.snapshot()
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
            status["last_run"] = _serialize_bot_run(last_run) if last_run else None
        return status

    # -- internal -----------------------------------------------------------

    def _construct_runtime(self, strategy_path, symbol, interval, mode, warmup_bars):
        try:
            return self._runtime_factory(
                strategy_path=strategy_path,
                symbol=symbol,
                interval=interval,
                mode=mode,
                live_data=True,
                warmup_bars=warmup_bars,
            )
        except Exception as e:
            logger.exception("Failed to create runtime")
            return {"status": "rejected", "message": f"Failed to create runtime: {e}"}

    def _start_session(self, runtime, strategy_path, symbol, interval, mode):
        if mode in ("testnet", "live"):
            if self._create_bot_config is None or self._settings is None:
                return {
                    "status": "rejected",
                    "message": "Config factory + settings required for testnet/live.",
                }
            config = self._create_bot_config(self._settings)
            result = runtime.start_live(strategy_path, symbol, interval, config)
            if result.status != "running":
                return {"status": "rejected", "message": result.message}
            return result.message
        return runtime.start(strategy_path, symbol, interval)

    def _run_forever(self) -> None:
        try:
            self._state.runtime.run_forever()  # type: ignore[union-attr]
        except Exception:
            logger.exception("Runtime thread crashed")
        finally:
            self._live_state.update(running=False)


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
