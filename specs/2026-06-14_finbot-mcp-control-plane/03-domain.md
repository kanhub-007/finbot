# Domain Model — Finbot MCP Control Plane

## Domain Entities

| Entity | Fields | Behaviour | Persisted? |
|--------|--------|-----------|------------|
| `BotRun` | run_id, strategy_name, strategy_hash, symbol, interval, mode, started_at, ended_at | Existing entity — represents a bot execution session | Yes (SQLite `bot_runs` table) |
| `BotConfig` | mode, live_trading_ack, max_position_usd, max_daily_loss_usd, max_open_orders, stale_data_seconds, private_key, db_path | Existing entity — validated domain-level config | No (derived from Settings at startup) |
| `TradingMode` | DRY_RUN, TESTNET, LIVE | Existing StrEnum — execution mode | No |
| `ProcessedSignal` | signal_key, bot_run_id, signal_action, bar_timestamp | Existing — one per candle where strategy returned non-HOLD | Yes (SQLite) |
| `OrderIntent` | intent_id, symbol, side, size, order_type, reduce_only, cloid, timestamp | Existing — persisted before exchange submission | Yes (SQLite) |
| `OrderResponseRecord` | intent_id, order_id, status, exchange_response_json, timestamp | Existing — exchange response for an intent | Yes (SQLite) |
| `FillRecord` | fill_id, order_id, symbol, side, size, price, fee, timestamp | Existing — trade fill from exchange | Yes (SQLite) |
| `RiskEventRecord` | bot_run_id, event_type, signal_key, decision, reason, timestamp | Existing — risk gate decision | Yes (SQLite) |
| `AuditLogEntry` | bot_run_id, event_type, event_data_json, timestamp | Existing — append-only audit trail | Yes (SQLite) |

## New Value Objects / DTOs

| Name | Fields | Used where |
|------|--------|------------|
| `BotStatusSnapshot` (new) | is_running, bot_run_id, strategy_name, strategy_hash, symbol, interval, mode, uptime_seconds, last_candle_timestamp, last_signal_action, last_signal_timestamp, last_order_status, open_position_size, position_direction, total_signals, total_orders, total_fills, warmup_ready | Returned by `get_bot_status`. Combines live runtime state + repository counts. |
| `StartBotRequest` (new) | strategy_path, symbol, interval, mode, warmup_bars, live_trading_ack | Input DTO for `start_bot` tool |
| `StartBotResult` (new) | status ("running"/"rejected"), bot_run_id, message | Output DTO for `start_bot` tool |
| `StopBotResult` (new) | status ("stopped"/"no_bot_running"), bot_run_id | Output DTO for `stop_bot` tool |
| `RunSummary` (new) | run_id, strategy_name, symbol, interval, mode, started_at, ended_at, signal_count, order_count, fill_count | Output DTO for `list_bot_runs` |
| `RunResults` (new) | run: RunSummary, signals: list[dict], orders: list[dict], fills: list[dict], risk_events: list[dict] | Output DTO for `get_bot_run_results` |

## New Domain Services

### `BotManager`

The `BotManager` is a domain service that owns the running bot instance.
It is the single source of truth for "is a bot running?" and provides
thread-safe access to the bot's state and lifecycle.

```
class BotManager:
    """Manages a single bot instance lifecycle with thread-safe state access."""

    - start(request: StartBotRequest) -> StartBotResult
    - stop() -> StopBotResult
    - get_status() -> BotStatusSnapshot
    - is_running() -> bool

    # Internal
    - _runtime: LiveTradingRuntimeUseCase | None   # set by start(), cleared by stop()
    - _thread: threading.Thread | None              # background thread for run_forever()
    - _state: BotLiveState                          # thread-safe live state container
    - _lock: threading.Lock                         # guards _runtime/_thread transitions
    - _repo: BotStateRepository                     # for historical queries
    - _exchange: ExchangeGateway                    # for status (position, open orders)
```

**Thread safety design:**
- `start()` acquires `_lock`, checks `_runtime is None`, creates and starts thread, releases lock.
- `stop()` acquires `_lock`, calls `_runtime.stop()`, joins thread, clears references, releases lock.
- `get_status()` acquires `_lock` briefly to read `_runtime` reference, then reads `_state` (atomic reads) and `_repo` queries without the lock.
- `BotLiveState` uses a simple lock or `threading.Event` for the `running` flag; numeric fields are updated atomically by the runtime thread and read by the MCP thread.

### `BotLiveState`

Thread-safe container for live runtime state that the MCP thread reads while
the runtime thread writes:

```
class BotLiveState:
    running: bool                 # Set True when thread starts, False when thread exits
    current_candle_timestamp: int # Last closed candle timestamp processed
    last_signal_action: str       # Last signal action from strategy evaluation
    last_signal_timestamp: str    # Timestamp of last signal
    last_order_status: str        # Last order response status
    warmup_ready: bool            # Whether warmup window has enough bars
```

**Thread safety:** Uses `threading.Lock` for writes; reads are lock-free
(reading stale values is acceptable for a status snapshot — eventual
consistency is fine here).

## Interfaces (for DI)

### `BotLoop` (existing)
Already exists in `core/domain/interfaces/bot_loop.py`. The `LiveTradingRuntimeUseCase`
uses it via `run_forever()` and `stop()`. The `BotManager` interacts with the
runtime use case, not the bot loop directly.

### `BotStateRepository` (existing)
Already exists. `BotManager` uses it for:
- `get_latest_bot_run()` — for status when no bot is running
- `count_signals()`, `count_orders()`, `count_fills()` — for status counts
- Query methods needed for `get_bot_run_results` — may need to add:
  - `list_bot_runs(limit, mode_filter)` — list runs with summaries
  - `get_signals_for_run(run_id)` — all signals for a run
  - `get_orders_for_run(run_id)` — all orders for a run
  - `get_fills_for_run(run_id)` — all fills for a run
  - `get_risk_events_for_run(run_id)` — all risk events for a run

### `ExchangeGateway` (existing)
Used by `BotManager.get_status()` to query:
- `get_position(symbol)` — current position
- `list_open_orders(symbol)` — current open orders

## Entity vs ORM Separation

All entities already follow the pattern:
- Domain entity: `finbot/core/domain/entities/*.py` — pure dataclass
- ORM model: `finbot/infrastructure/repositories/sqlite_*.py` or ORM tables
- Mapper: within repository implementations

No new entities break this pattern. New DTOs (StartBotRequest, BotStatusSnapshot,
etc.) are pure dataclasses in `core/application/dto/`.

## Files to Add/Modify

### New Files

| File | Layer | Contents |
|------|-------|----------|
| `finbot/core/domain/services/bot_manager.py` | Domain | `BotManager` class |
| `finbot/core/domain/services/bot_live_state.py` | Domain | `BotLiveState` thread-safe container |
| `finbot/core/application/dto/start_bot_request.py` | Application | `StartBotRequest` DTO |
| `finbot/core/application/dto/start_bot_result.py` | Application | `StartBotResult` DTO |
| `finbot/core/application/dto/stop_bot_result.py` | Application | `StopBotResult` DTO |
| `finbot/core/application/dto/bot_status_snapshot.py` | Application | `BotStatusSnapshot` DTO |
| `finbot/core/application/dto/run_summary.py` | Application | `RunSummary` DTO |
| `finbot/core/application/dto/run_results.py` | Application | `RunResults` DTO |

### Modified Files

| File | Change |
|------|--------|
| `finbot/core/domain/interfaces/bot_state_repository.py` | Add `list_bot_runs`, `get_signals_for_run`, `get_orders_for_run`, `get_fills_for_run`, `get_risk_events_for_run`, `get_audit_log` methods |
| `finbot/infrastructure/repositories/in_memory_bot_state_repository.py` | Implement new repository methods |
| `finbot/infrastructure/repositories/sqlite_bot_state_repository.py` | Implement new repository methods |
| `pyproject.toml` | Add `fastmcp` to optional dependencies |
