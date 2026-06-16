# Implementation Guide — Multi-Ticker Portfolio Runtime

Build order follows TDD Red → Green → Refactor per scenario, sliced so each
slice is independently shippable and the single-symbol runtime never breaks.

**Golden rule:** after every step, `ruff check finbot tests && black finbot
tests && pytest tests` must pass. The existing architecture test
(`tests/test_architecture/test_dependency_rules.py`) must stay green — no
domain file imports infrastructure, finbar, hyperliquid, sqlalchemy, or
fastapi.

---

## Slice 1 — MVP

### Step 1: Add `Trade` entity + lifecycle (Scenario S7)
**File:** `finbot/core/domain/entities/trade.py`
**Files:** `finbot/core/domain/services/trade_lifecycle.py`

Pure dataclass + pure transition functions. No persistence yet.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_domain/test_trade_lifecycle.py -q
```
- `test_apply_entry_fill_sets_opened_fields`
- `test_apply_exit_fill_computes_realized_pnl_long`  ((close-entry)*size)
- `test_apply_exit_fill_computes_realized_pnl_short` ((entry-close)*size)
- `test_update_extremes_tracks_max_favorable_and_adverse`
**Common mistake:** using `float` for pnl — use `Decimal`.

### Step 2: Extend `BotStateRepository` with Trade methods
**File:** `finbot/core/domain/interfaces/bot_state_repository.py`

Add the eight methods listed in 03-domain.md.

**Verify:** existing repo tests must still compile/pass (interface grew).

### Step 3: Implement Trade persistence (in-memory first)
**Files:** `finbot/infrastructure/repositories/in_memory_bot_state_repository.py`
**File:** `finbot/infrastructure/repositories/trade_mapper.py`

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_infrastructure/test_in_memory_bot_state_repository.py -q
```
- `test_open_trade_then_get_open_trade_for_symbol`
- `test_close_trade_sets_status_and_realized_pnl`
- `test_count_open_trades_across_symbols`
**Common mistake:** forgetting `list_open_trades` must be ordered deterministically.

### Step 4: `TradeBook` domain service (Scenario S3, S4)
**File:** `finbot/core/domain/services/trade_book.py`

Thin facade over repo that answers portfolio queries.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_domain/test_trade_book.py -q
```
- `test_gross_notional_sums_absolute_values_across_long_and_short`
- `test_count_open_returns_zero_when_book_empty`
- `test_daily_realized_loss_aggregates_closed_today`

### Step 5: Portfolio risk gates (Scenarios S3, S4, S11)
**Files:** `finbot/core/domain/services/risk_gates/max_open_positions_gate.py`
**Files:** `finbot/core/domain/services/risk_gates/max_gross_notional_gate.py`

Same `RiskGate` interface. Exit signals bypass.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_domain/test_max_open_positions_gate.py \
                  tests/test_domain/test_max_gross_notional_gate.py -q
```
- `test_max_open_positions_rejects_when_portfolio_full`
- `test_max_open_positions_passes_exit_signal_even_when_full`
- `test_disabled_when_max_is_zero`
- `test_max_gross_notional_rejects_oversized_book`
**Common mistake:** forgetting exits must bypass — would lock the book open.

### Step 6: `SymbolSetProvider` interface + static impl (Scenario S1)
**File:** `finbot/core/domain/interfaces/symbol_set_provider.py`
**File:** `finbot/core/domain/services/static_symbol_set_provider.py`

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_domain/test_static_symbol_set_provider.py -q
```
- `test_static_provider_returns_configured_symbols`
- `test_static_provider_dedupes_and_uppercases`
- `test_refresh_is_noop_for_static`

### Step 7: Extract `SymbolPipeline` from `LiveTradingRuntimeUseCase`
**File:** `finbot/core/domain/services/symbol_pipeline.py`

Move the per-symbol body of `process_closed_candle` (warmup → enrich →
validate → evaluate) plus the risk/plan/persist/submit tail into this class,
parameterised by `symbol`. The existing `LiveTradingRuntimeUseCase` becomes a
thin wrapper that holds one `SymbolPipeline` — keeping its tests green.

**Verify:** full single-symbol suite green (no behaviour change):
```bash
PYTHONPATH=. pytest tests/test_application/test_live_trading_runtime.py \
                  tests/test_application/test_bot_loop_integration.py -q
```
**Common mistake:** changing behaviour while refactoring. Diff the pipeline
output against the old use case on the same fakes; results must be identical.

### Step 8: Extend `BotLoop` interface + `BotEventLoop` for multi-symbol (S2, S10)
**File:** `finbot/core/domain/interfaces/bot_loop.py` (signature change)
**File:** `finbot/infrastructure/adapters/bot_event_loop.py`

Subscribe once per symbol on the shared stream; tag each candle with its
symbol; demux into `on_candle(symbol, candle)`. Per-symbol failure marks that
symbol degraded, does not abort the loop.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_infrastructure/test_bot_event_loop.py -q
```
- `test_subscribes_to_all_symbols_on_start`
- `test_demuxes_candle_to_correct_symbol_callback`
- `test_unknown_symbol_candle_is_dropped_not_raised`
- `test_one_symbol_failure_does_not_stop_others`
**Common mistake:** changing the single-symbol call sites without updating them all.

### Step 9: `PortfolioTradingRuntimeUseCase` coordinator (S1, S2, S5)
**File:** `finbot/core/application/use_cases/portfolio_trading_runtime.py`

Demux `process_closed_candle(symbol, candle)` → `pipelines[symbol]`, build
portfolio context, run the shared gate chain (portfolio gates first).

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_application/test_portfolio_runtime.py -q
```
- `test_start_creates_one_run_covering_all_symbols` (S1)
- `test_candle_for_eth_does_not_touch_btc_warmup` (S2)
- `test_duplicate_candle_idempotent_per_symbol` (S5)
- `test_empty_symbol_set_rejected` (S9)
**Common mistake:** building portfolio context once at start instead of per
candle (open-position count changes every fill).

### Step 10: Startup reconciliation for all symbols (S6)
Extend `PortfolioTradingRuntimeUseCase.reconcile_on_startup`.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_application/test_portfolio_runtime.py::test_reconcile_all_symbols -q
```
- fetch positions + open orders for every symbol
- reconstruct Trade for any open exchange position
- flag exchange/DB mismatches in audit log
- one symbol's failure does not abort others

### Step 11: Kill switch across the portfolio (S8)
**File:** `PortfolioTradingRuntimeUseCase.kill_switch`

**Verify:**
- `test_cancel_all_cancels_every_symbol`
- `test_close_all_reduces_only_market_closes`
- `test_partial_failure_reports_per_symbol_errors`
- `test_kill_switch_idempotent`

### Step 12: SQLite Trade table + migration
**File:** `finbot/infrastructure/repositories/sqlite_bot_state_repository.py`
**File:** `finbot/infrastructure/repositories/sqlite_migrator.py`

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_infrastructure/test_database_migrations.py \
                  tests/test_infrastructure/test_sqlite_bot_state_repository.py -q
```
**Common mistake:** migration must be idempotent and run on existing DBs.

### Step 13: Wire startup + MCP tools
**File:** `finbot/startup/service_factory.py` (portfolio factory + gate chain)
**File:** `finbot/core/domain/services/bot_manager.py` (own portfolio runtime)
**File:** `finbot/presentation/mcp/tools/bot_control.py` (`start_portfolio`,
`kill_switch`, `portfolio_status`)

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_startup/test_service_factory.py \
                  tests/test_presentation/test_mcp_tools.py -q
PYTHONPATH=. python finbot/presentation/cli/main.py portfolio-status --help
```

### Step 14: Slice 1 review gate
Run all four reviews from AGENTS.md §6:
```bash
# /review_quality all portfolio-runtime scope
# /review_logic  all portfolio-runtime scope
# /review_security all portfolio-runtime scope  (esp. kill switch, live ack)
# /review_performance all portfolio-runtime scope (per-candle context cost)
# /review_tests all portfolio-runtime scope
PYTHONPATH=. pytest tests -q
```
Fix everything before Slice 2.

---

## Slice 2 — Should

### Step 15: Per-symbol last-candle-seen short-circuit (S12)
Track `last_analyzed_timestamp` per pipeline; skip enrichment when unchanged.
**Verify:** `test_skip_recompute_when_candle_ts_unchanged`.

### Step 16: Orphaned-exit safety (S13)
`active_symbols() = static_set ∪ symbols_with_open_trades`. Refresh does not
evict symbols that hold open positions.
**Verify:** `test_dropped_symbol_with_open_trade_stays_active`.

### Step 17: Batched warmup fetch (S14)
Hyperliquid `candle_snapshot` accepts multiple coins. One call fills N
pipelines. `BarSource` gains a batch method.
**Verify:** `test_warmup_uses_one_batched_call_for_n_symbols`.

### Step 18: Aggregated status snapshot (S15)
`portfolio_status()` DTO wired to MCP.
**Verify:** `test_portfolio_status_aggregates_per_symbol_and_totals`.

---

## Slice 3 — Could

### Step 19: `MarketDataProvider` (S17)
Hoist per-symbol warmup + enriched frames out of pipelines into a shared
provider. Enables cross-symbol informative data.
**Verify:** pipelines still pass Slice 1 tests unchanged.

### Step 20: Dynamic pairlist providers (S16)
`VolumePairlistProvider`, `SpreadFilter`, etc. — `SymbolSetProvider` impls.
**Verify:** `test_volume_pairlist_excludes_below_threshold`.

### Step 21: Per-symbol strategy assignment (S18)
A `strategy_assignment: dict[str, str]` on `StartPortfolioRequest`; each
pipeline gets its own evaluator. Portfolio risk still spans all.
**Verify:** new spec or extend this one first — confirm before building.
