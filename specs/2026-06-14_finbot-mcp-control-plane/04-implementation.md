# Implementation Guide — Finbot MCP Control Plane

Implementation follows TDD (Red → Green → Refactor) per scenario, ordered by
slice and MoSCoW priority. Each step includes the files to create/modify,
the test to write first, and what to watch out for.

---

## Slice 1: MVP — Start/Stop/Status (Must)

### Step 1: Add fastmcp dependency

**File:** `pyproject.toml`

Add `fastmcp` under `[project.optional-dependencies]` and to `dev` so tests
can import it:

```toml
[project.optional-dependencies]
dev = [
    "black>=24.0.0",
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "ruff>=0.6.0",
    "fastmcp>=2.0.0",
]
mcp = [
    "fastmcp>=2.0.0",
]
```

**Verify:** `python -m pip install -e ".[dev]"` and `python -c "import fastmcp; print(fastmcp.__version__)"`

**Common mistake:** Don't add fastmcp to core dependencies — it's optional.

---

### Step 2: Add new repository query methods to the interface

**File:** `finbot/core/domain/interfaces/bot_state_repository.py`

Add abstract methods for the historical queries needed by MCP tools:

```python
@abstractmethod
def list_bot_runs(
    self, limit: int = 20, mode_filter: str | None = None
) -> list[BotRun]:
    """Return recent bot runs ordered by started_at DESC."""

@abstractmethod
def get_signals_for_run(self, run_id: str) -> list[ProcessedSignal]:
    """Return all signals for a specific bot run."""

@abstractmethod
def get_orders_for_run(self, run_id: str) -> list[OrderResponseRecord]:
    """Return all order responses for a specific bot run."""

@abstractmethod
def get_fills_for_run(self, run_id: str) -> list[FillRecord]:
    """Return all fills for a specific bot run."""

@abstractmethod
def get_risk_events_for_run(self, run_id: str) -> list[RiskEventRecord]:
    """Return all risk events for a specific bot run."""

@abstractmethod
def get_audit_log(
    self, limit: int = 50, event_type: str | None = None
) -> list[AuditLogEntry]:
    """Return recent audit log entries."""
```

**Verify:** Ruff/pyright pass. Both `InMemoryBotStateRepository` and
`SqliteBotStateRepository` will fail type checking until implemented —
that's expected (Red phase).

---

### Step 3: Implement new methods in InMemoryBotStateRepository

**File:** `finbot/infrastructure/repositories/in_memory_bot_state_repository.py`

Add in-memory implementations for all new abstract methods. Each should:
- Store data in `self._bot_runs`, `self._signals`, etc. (existing dicts)
- Filter by run_id where applicable
- Return empty lists for missing runs (never raise)

**Verify:** Existing tests still pass. Unit test for new methods:
`tests/test_infrastructure/test_in_memory_bot_state_repository.py`

---

### Step 4: Implement new methods in SqliteBotStateRepository

**File:** `finbot/infrastructure/repositories/sqlite_bot_state_repository.py`

Add SQL implementations for the new query methods:
- `list_bot_runs` → SELECT from `bot_runs` ORDER BY started_at DESC LIMIT
- `get_signals_for_run` → SELECT from signals WHERE bot_run_id = ?
- etc.

**Verify:** Unit test against a temporary SQLite database.

---

### Step 5: Create BotLiveState

**File:** `finbot/core/domain/services/bot_live_state.py`

```python
"""Thread-safe container for live bot state."""

import threading
from dataclasses import dataclass, field


@dataclass
class BotLiveState:
    """Mutable state shared between runtime thread and status reader thread."""

    running: bool = False
    bot_run_id: str = ""
    strategy_name: str = ""
    symbol: str = ""
    interval: str = ""
    mode: str = ""
    current_candle_timestamp: int = 0
    last_signal_action: str = ""
    last_signal_timestamp: str = ""
    last_order_status: str = ""
    warmup_ready: bool = False
    # Trade/position state
    open_position_size: float = 0.0
    position_direction: str = "flat"
    open_order_count: int = 0
    # Cumulative counts
    total_signals: int = 0
    total_orders: int = 0
    total_fills: int = 0

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, **kwargs) -> None:
        """Thread-safe batch update of fields."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    def snapshot(self) -> dict:
        """Return a thread-safe snapshot as a dict."""
        with self._lock:
            return {
                "running": self.running,
                "bot_run_id": self.bot_run_id,
                "strategy_name": self.strategy_name,
                "symbol": self.symbol,
                "interval": self.interval,
                "mode": self.mode,
                "current_candle_timestamp": self.current_candle_timestamp,
                "last_signal_action": self.last_signal_action,
                "last_signal_timestamp": self.last_signal_timestamp,
                "last_order_status": self.last_order_status,
                "warmup_ready": self.warmup_ready,
                "open_position_size": self.open_position_size,
                "position_direction": self.position_direction,
                "open_order_count": self.open_order_count,
                "total_signals": self.total_signals,
                "total_orders": self.total_orders,
                "total_fills": self.total_fills,
            }
```

**Verify:** `python -m pytest tests/test_domain/test_bot_live_state.py -v`

**Common mistake:** Don't over-engineer locking. A single lock for the whole
struct is fine — status reads are infrequent and the struct is small.

---

### Step 6: Create BotManager

**File:** `finbot/core/domain/services/bot_manager.py`

The `BotManager` owns the running bot lifecycle. It lives in `core/domain/services/`
because it's pure orchestration — it depends only on domain interfaces and the
`startup/` layer wires the concrete implementations.

```python
"""Manages a single bot instance lifecycle with thread-safe state."""

import threading
import time
from pathlib import Path

from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.interfaces.bot_state_repository import BotStateRepository
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.services.bot_live_state import BotLiveState


class BotManager:
    """Owns the lifecycle of a single bot runtime instance.

    Only one bot can run at a time. Thread-safe for start/stop/status
    calls from the MCP thread while the runtime runs in a background thread.
    """

    def __init__(
        self,
        runtime_factory,  # callable -> LiveTradingRuntimeUseCase
        repository: BotStateRepository,
        exchange: ExchangeGateway,
        settings,  # Settings
        startup_time: float,
    ) -> None:
        self._runtime_factory = runtime_factory
        self._repo = repository
        self._exchange = exchange
        self._settings = settings
        self._startup_time = startup_time
        self._state = BotLiveState()
        self._runtime = None  # type: LiveTradingRuntimeUseCase | None
        self._thread = None   # type: threading.Thread | None
        self._lock = threading.Lock()

    def start(
        self,
        strategy_path: str,
        symbol: str,
        interval: str,
        mode: str,
        warmup_bars: int = 100,
        live_trading_ack: bool = False,
    ) -> dict:
        """Start a bot in a background thread."""
        with self._lock:
            if self._runtime is not None:
                return {"status": "rejected",
                        "message": "Bot already running. Stop it first."}

            # Validate inputs
            if not Path(strategy_path).exists():
                return {"status": "rejected",
                        "message": f"Strategy file not found: {strategy_path}"}

            if mode not in ("dry_run", "testnet", "live"):
                return {"status": "rejected",
                        "message": f"Invalid mode: {mode}"}

            # Build runtime
            runtime = self._runtime_factory(
                strategy_path=strategy_path,
                symbol=symbol,
                interval=interval,
                mode=mode,
                live_data=True,
                warmup_bars=warmup_bars,
            )

            # Start session
            if mode in ("testnet", "live"):
                from finbot.startup.service_factory import create_bot_config
                config = create_bot_config(self._settings)
                result = runtime.start_live(strategy_path, symbol, interval, config)
                if result.status != "running":
                    return {"status": "rejected",
                            "message": result.message,
                            "bot_run_id": result.message.replace("; ", "\n")}
                bot_run_id = result.message
            else:
                bot_run_id = runtime.start(strategy_path, symbol, interval)

            self._runtime = runtime
            self._state.update(
                running=True,
                bot_run_id=bot_run_id,
                strategy_name=strategy_path,
                symbol=symbol,
                interval=interval,
                mode=mode,
            )

            # Start background thread
            self._thread = threading.Thread(
                target=self._run_forever,
                name="finbot-runtime",
                daemon=True,
            )
            self._thread.start()

            return {"status": "running", "bot_run_id": bot_run_id}

    def stop(self) -> dict:
        """Stop the running bot and join its thread."""
        with self._lock:
            if self._runtime is None:
                return {"status": "no_bot_running", "bot_run_id": ""}

            runtime = self._runtime
            self._runtime = None
            self._state.update(running=False)

        # Stop outside the lock to avoid deadlock if stop() triggers callbacks
        runtime.stop()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

        return {"status": "stopped", "bot_run_id": self._state.bot_run_id}

    def get_status(self) -> dict:
        """Return a live status snapshot."""
        with self._lock:
            is_running = self._runtime is not None

        status = self._state.snapshot()
        status["is_running"] = is_running
        status["uptime_seconds"] = time.time() - self._startup_time

        if not is_running:
            last_run = self._repo.get_latest_bot_run()
            if last_run:
                status["last_run"] = {
                    "run_id": last_run.run_id,
                    "strategy_name": last_run.strategy_name,
                    "symbol": last_run.symbol,
                    "interval": last_run.interval,
                    "mode": last_run.mode,
                    "started_at": last_run.started_at.isoformat() if last_run.started_at else None,
                    "ended_at": last_run.ended_at.isoformat() if last_run.ended_at else None,
                }
            else:
                status["last_run"] = None

        # Append repository-sourced counts
        status["total_signals"] = max(
            status.get("total_signals", 0), self._repo.count_signals()
        )
        status["total_orders"] = max(
            status.get("total_orders", 0), self._repo.count_orders()
        )
        status["total_fills"] = max(
            status.get("total_fills", 0), self._repo.count_fills()
        )

        return status

    def is_running(self) -> bool:
        with self._lock:
            return self._runtime is not None

    def _run_forever(self) -> None:
        """Target for the background runtime thread."""
        try:
            if self._runtime:
                self._runtime.run_forever()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Runtime thread crashed")
        finally:
            self._state.update(running=False)
```

**Verify:** `python -m pytest tests/test_domain/test_bot_manager.py -v`

**Common mistake:** Don't call `runtime.stop()` inside the lock — it can
trigger callbacks that try to acquire the same lock, causing deadlock.
Acquire lock, extract reference, release lock, then stop.

---

### Step 7: Wire BotManager + integrate with LiveTradingRuntime state updates

**File:** `finbot/core/application/use_cases/live_trading_runtime.py` (modify)

Add an optional `live_state: BotLiveState | None = None` parameter to
`LiveTradingRuntimeUseCase.__init__()`. When set, the runtime updates
the `live_state` on key events:

In `process_closed_candle()`:
```python
if self._live_state:
    self._live_state.update(
        current_candle_timestamp=ts,
        warmup_ready=self._warmup.is_ready(),
    )
```

In `_plan_and_persist()`:
```python
if self._live_state:
    self._live_state.update(
        last_signal_action=signal.action.value,
        last_signal_timestamp=str(candle_ts),
    )
```

In `_dispatch_submission()` after recording the order:
```python
if self._live_state:
    self._live_state.update(
        last_order_status="submitted" if submitted else "dry_run_recorded",
        open_order_count=...,
    )
```

**Verify:** Test that `BotLiveState` fields are populated during a dry-run.

---

### Step 8: Create MCP tools — bot_control.py

**File:** `finbot/presentation/mcp/tools/bot_control.py`

Register `start_bot`, `stop_bot`, and `get_bot_status` tools on the FastMCP
server instance:

```python
"""MCP tools for bot lifecycle control."""

import json

from fastmcp import FastMCP


def register_bot_control_tools(mcp: FastMCP) -> None:
    """Register start/stop/status MCP tools."""

    @mcp.tool(
        name="start_bot",
        description=(
            "Start a Finbot trading runtime with a YAML strategy. "
            "Supports dry_run (paper trading), testnet (testnet execution), "
            "and live modes. Only one bot can run at a time. "
            "Use live_trading_ack=true when starting testnet/live mode."
        ),
    )
    def start_bot(
        strategy_path: str,
        symbol: str = "BTC",
        interval: str = "1h",
        mode: str = "dry_run",
        warmup_bars: int = 100,
        live_trading_ack: bool = False,
    ) -> str:
        """Start a bot."""
        manager = _get_bot_manager()
        result = manager.start(
            strategy_path=strategy_path,
            symbol=symbol,
            interval=interval,
            mode=mode,
            warmup_bars=warmup_bars,
            live_trading_ack=live_trading_ack,
        )
        return json.dumps(result, indent=2)

    @mcp.tool(
        name="stop_bot",
        description=(
            "Stop the currently running bot. Safe to call when no bot "
            "is running — returns 'no_bot_running' status."
        ),
    )
    def stop_bot() -> str:
        """Stop the bot."""
        return json.dumps(_get_bot_manager().stop(), indent=2)

    @mcp.tool(
        name="get_bot_status",
        description=(
            "Get the current bot status. If a bot is running, returns live "
            "state including last candle timestamp, last signal, position, "
            "and cumulative counts. If no bot is running, returns summary "
            "of the most recently completed run."
        ),
    )
    def get_bot_status() -> str:
        """Return bot status."""
        return json.dumps(_get_bot_manager().get_status(), indent=2)
```

The `_get_bot_manager()` helper accesses the `BotManager` singleton stored on
the FastMCP app instance. Follow the finbar pattern: store it as
`mcp._finbot_bot_manager` during composition.

---

### Step 9: Create MCP tools aggregator

**File:** `finbot/presentation/mcp/tools/__init__.py`

```python
"""MCP tools — finbot operations exposed to MCP clients."""

from fastmcp import FastMCP

from .bot_control import register_bot_control_tools


def register_tools(mcp: FastMCP) -> None:
    """Register all finbot MCP tools on the given server instance."""
    register_bot_control_tools(mcp)
```

---

### Step 10: Create MCP composition root

**File:** `finbot/startup/mcp.py`

Following the exact pattern from finbar and kapsula:

```python
"""MCP server startup — composition root for the MCP transport.

Creates the FastMCP server, wires dependencies, and provides the CLI runner.
"""

import logging
import os
import time

from dotenv import load_dotenv
from fastmcp import FastMCP

from finbot.config.settings import Settings
from finbot.core.domain.services.bot_manager import BotManager
from finbot.startup.service_factory import (
    create_bot_state_repository,
    create_exchange_gateway,
    create_live_trading_runtime_use_case,
)

load_dotenv()
logger = logging.getLogger(__name__)


def _make_runtime_factory(settings: Settings):
    """Return a callable that creates a LiveTradingRuntimeUseCase."""
    def factory(strategy_path, symbol, interval, mode, live_data, warmup_bars):
        return create_live_trading_runtime_use_case(
            strategy_path=strategy_path,
            symbol=symbol,
            interval=interval,
            mode=mode,
            live_data=live_data,
            warmup_bars=warmup_bars,
        )
    return factory


def create_server() -> FastMCP:
    """Build the FastMCP server with all dependencies wired.

    Returns:
        Configured FastMCP server instance ready to run.
    """
    settings = Settings()
    repo = create_bot_state_repository(migrate=True)
    exchange = create_exchange_gateway(settings)

    bot_manager = BotManager(
        runtime_factory=_make_runtime_factory(settings),
        repository=repo,
        exchange=exchange,
        settings=settings,
        startup_time=time.time(),
    )

    server = FastMCP(
        name="finbot",
        instructions=(
            "Finbot is a live trading runtime for Finbar YAML strategies. "
            "It connects to Hyperliquid and executes trading strategies. "
            "\n\n"
            "QUICK REFERENCE:\n"
            "• start_bot(): Start a trading bot with a strategy file.\n"
            "• get_bot_status(): Check current bot state, position, signals.\n"
            "• stop_bot(): Stop the running bot safely.\n"
            "• validate_strategy(): Check a strategy file before running.\n"
            "• list_bot_runs(): See completed bot runs.\n"
            "• get_bot_run_results(): Get detailed results from a run.\n"
            "• panic(): Emergency stop + cancel orders.\n"
            "• ping(): Health check.\n"
        ),
    )

    # Store bot_manager on the server instance so tools can access it
    server._finbot_bot_manager = bot_manager

    # Register all tools
    from finbot.presentation.mcp.tools import register_tools
    register_tools(server)

    config = get_transport_config()
    logger.info("MCP server configured: transport=%s", config["transport"])
    if config["transport"] == "http":
        logger.info("HTTP transport: %s:%s", config["host"], config["port"])

    return server


def get_transport_config() -> dict:
    """Read transport configuration from environment variables."""
    return {
        "transport": os.getenv("FINBOT_TRANSPORT", "stdio").lower(),
        "host": os.getenv("FINBOT_HOST", "127.0.0.1"),
        "port": int(os.getenv("FINBOT_PORT", "8003")),
    }


def run() -> None:
    """Start the MCP server. Called by CLI entry points."""
    server = create_server()
    config = get_transport_config()

    if config["transport"] == "http":
        logger.info(
            "Starting MCP server on http://%s:%s",
            config["host"],
            config["port"],
        )
        server.run(
            transport="streamable-http",
            host=config["host"],
            port=config["port"],
        )
    else:
        logger.info("Starting MCP server on stdio")
        server.run(transport="stdio")
```

**Verify:** `python -c "from finbot.startup.mcp import create_server; s = create_server(); print('OK')"`

---

### Step 11: Create convenience entry point

**File:** `run_mcp.py`

```python
"""Convenience entry point — run with: python run_mcp.py

Starts the MCP server. Defaults to stdio transport.
Set FINBOT_TRANSPORT=http to run on port 8003.

All startup logic lives in finbot/startup/mcp.py (composition root).
"""

from finbot.startup.mcp import run

if __name__ == "__main__":
    run()
```

---

## Slice 2: Historical Results (Should)

### Step 12: Add bot_history MCP tools

**File:** `finbot/presentation/mcp/tools/bot_history.py`

Register `list_bot_runs` and `get_bot_run_results` tools. Pattern follows
`bot_control.py` — use `_get_bot_manager()` to access the repository.

**Verify:** Integration test with fake repository containing known runs.

---

## Slice 3: Safety & Lifecycle (Should)

### Step 13: Add safety MCP tools

**File:** `finbot/presentation/mcp/tools/safety.py`

Register `panic` tool. Stops the bot, then calls exchange gateway
`cancel_all()` and optionally `close_position()`. Panic bypasses
risk gates (intentional — kill switch).

### Step 14: Add utility MCP tools

**File:** `finbot/presentation/mcp/tools/util.py`

Register `ping` and `validate_strategy` tools.

---

## Test Structure

```
tests/
├── test_domain/
│   ├── test_bot_live_state.py       # Thread safety + snapshot
│   └── test_bot_manager.py          # Lifecycle with fakes
├── test_presentation/
│   └── test_mcp/
│       ├── test_bot_control_tools.py # start/stop/status via MCP
│       ├── test_bot_history_tools.py # list_runs, get_run_results
│       └── conftest.py              # Shared MCP test fixtures
└── test_infrastructure/
    └── test_in_memory_bot_state_repository.py  # Extended with new methods
```

---

## Key Architecture Decisions

### Why BotManager in core/domain/services/ instead of infrastructure?

`BotManager` orchestrates domain interfaces (`BotStateRepository`,
`ExchangeGateway`) and a domain service (`BotLiveState`). It does not depend
on any framework, SDK, or infrastructure. The concrete `LiveTradingRuntimeUseCase`
is injected via a factory callable (DI), so `BotManager` stays pure. This
follows Clean Architecture: domain services depend on domain interfaces.

### Why a factory callable instead of constructing the runtime directly?

The runtime construction (`create_live_trading_runtime_use_case`) lives in
`startup/service_factory.py` because it needs `Settings`, which is
infrastructure-level. By injecting a factory, `BotManager` stays unaware of
how the runtime is built — it just calls the factory with the right arguments.

### Why store BotManager on the FastMCP instance instead of a module global?

Module globals make testing hard (can't reset state between tests). Storing
on the FastMCP instance (`server._finbot_bot_manager`) lets tests inject a
fake manager. The finbar pattern uses `_shared.py` with lazy factories;
finbot can follow the same pattern or use instance storage. Instance storage
is simpler and avoids circular imports.

### Thread safety — why simple locking?

Status reads are infrequent (human-driven or polled every few seconds).
A single `threading.Lock` for the whole struct is the simplest correct
solution. More granular locking would be premature optimization.
