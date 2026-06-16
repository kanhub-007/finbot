# Implementation Guide — Durable Trade Entity & Realized PnL

TDD Red → Green → Refactor per scenario, sliced. After every step:
`ruff check finbot tests && black finbot tests && pytest tests` must pass,
including the architecture test (no domain file imports infra/finbar/
hyperliquid/sqlalchemy).

---

## Slice 1 — MVP

### Step 1: `Trade` entity
**File:** `finbot/core/domain/entities/trade.py`

Pure frozen dataclass. Depends only on `PositionDirection` + stdlib.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_domain/test_trade.py -q
```
- `test_trade_default_status_is_open`
- `test_trade_is_frozen`

### Step 2: `TradeLifecycle` pure functions (Scenarios S1–S4)
**File:** `finbot/core/domain/services/trade_lifecycle.py`

`open_from_fill`, `apply_entry_fill`, `apply_exit_fill`, `realized_pnl_for_exit`,
`sign_for`. All pure; take/return frozen `Trade`.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_domain/test_trade_lifecycle.py -q
```
- `test_open_from_buy_fill_is_long` (S1)
- `test_open_from_sell_fill_is_short`
- `test_apply_entry_fill_weighted_average` (S3)
- `test_apply_exit_fill_long_profit` (S2)
- `test_apply_exit_fill_short_profit` (S4)
- `test_apply_exit_fill_loss_is_negative` (S4)
- `test_exit_fill_closes_when_size_reaches_zero` (S3)
- `test_partial_exit_keeps_trade_open` (S3)
- `test_pnl_net_of_fees`
**Common mistakes:** using `float` (use `Decimal`); wrong sign for short;
forgetting fees; closing before size hits 0.

### Step 3: Extend `BotStateRepository` interface
**File:** `finbot/core/domain/interfaces/bot_state_repository.py`

Add the 6 Trade methods (03-domain.md). Existing tests must still import/pass
(interface grew, no behaviour yet).

### Step 4: In-memory `Trade` persistence
**File:** `finbot/infrastructure/repositories/in_memory_bot_state_repository.py`

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_infrastructure/test_in_memory_bot_state_repository.py -q
```
- `test_open_then_get_open_trade`
- `test_update_trade_replaces_row`
- `test_list_open_trades_excludes_closed`
- `test_realized_loss_on_sums_negative_pnl_for_day` (S6)

### Step 5: `TradeLedger` accountant (Scenarios S1–S3, S9)
**File:** `finbot/core/domain/services/trade_ledger.py`
**File:** `finbot/core/domain/dto/fill_outcome.py`

Classification + delegation to `TradeLifecycle` + repo writes. **No own
transaction** — relies on caller's.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_domain/test_trade_ledger.py -q
```
- `test_entry_fill_opens_trade` (S1)
- `test_exit_fill_closes_with_realized_pnl` (S2)
- `test_partial_fills_accumulate_then_partial_close` (S3)
- `test_duplicate_fill_id_skipped` (S9)
- `test_replayed_exit_does_not_double_realize` (S9)
- `test_realized_loss_on_excludes_other_days` (S6)
**Common mistake:** opening a second Trade when one is already open for the
symbol (must accumulate or exit, never fork).

### Step 6: Wire `TradeLedger` into `AccountEventHandler` (ADR-6 atomicity)
**File:** `finbot/core/application/use_cases/account_event_handler.py`
**File:** `finbot/core/application/use_cases/live_trading_runtime.py`

1. Add `trade_ledger: TradeLedger | None = None` ctor param to
   `AccountEventHandler` (default `TradeLedger(repo)`).
2. Call `self._trade_ledger.apply_fill(fill)` **inside** the existing
   transaction in `_handle_fill`.
3. **Update the lazy construction site in `LiveTradingRuntimeUseCase.process_account_event`**
   (it currently builds the handler as `AccountEventHandler(self._repo)`):
   pass the runtime's `self._trade_ledger` as the second arg.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_application/test_account_events.py -q
```
- `test_fill_opens_trade_atomically_with_fill_record`
- `test_fill_idempotency_preserved_with_trade`
- existing account-event tests still pass

### Step 7: SQLite `trades` table + migration v3
**File:** `finbot/infrastructure/repositories/sqlite_migrator.py`
**File:** `finbot/infrastructure/repositories/sqlite_bot_state_repository.py`

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_infrastructure/test_database_migrations.py \
                  tests/test_infrastructure/test_sqlite_bot_state_repository.py \
                  tests/test_infrastructure/test_sqlite_trade_repository.py -q
```
- `test_migration_v3_creates_trades_table`
- `test_migration_idempotent_on_existing_db` (no data loss)
- `test_trade_round_trips_through_sqlite` (S7)
- `test_realized_loss_query_uses_index` (EXPLAIN plan, if feasible)

### Step 8: Real `daily_loss_usd` in the runtime + exit-bypass in the gate (THE FIX — S5, S6, S12)
**File:** `finbot/core/application/use_cases/live_trading_runtime.py`
**File:** `finbot/core/domain/services/risk_gates/daily_loss_gate.py`

**Part A — runtime:** inject `trade_ledger` into the runtime ctor; in
`_build_risk_context` replace the hardcoded `Decimal("0")` with
`self._trade_ledger.realized_loss_on(datetime.now(UTC).date())`.

**Part B — gate (behaviour change, not verification):** the current
`DailyLossGate` has **no exit bypass** (verified). It would reject
LONG_EXIT/SHORT_EXIT when over cap, locking the bot into losing positions.
**ADD** bypass at the top of `check()`:
```python
from finbot.core.domain.entities.signal_action import SignalAction
...
if signal.action in (SignalAction.LONG_EXIT, SignalAction.SHORT_EXIT):
    return RiskDecision(accepted=True, gate_name="daily_loss",
                        reason="exits bypass daily-loss cap")
```
Also fix the gate's docstring: "realized loss only" (it currently says
"realized + unrealized", which is inaccurate — see ADR-2).

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_domain/test_daily_loss_gate_functional.py \
                  tests/test_application/test_daily_loss_gate_e2e.py -q
```
- `test_gate_rejects_when_realized_loss_exceeds_cap` (S5)
- `test_gate_accepts_when_under_cap` (S5)
- `test_gate_resets_across_utc_midnight` (S6)
- `test_gate_does_not_block_exit_signals` (S5 also-test — proves the bypass)
- `test_e2e_runtime_rejects_entry_after_loss` (S12)

### Step 8b: NEW `reconcile_on_startup()` method (S8)
**File:** `finbot/core/application/use_cases/live_trading_runtime.py`

This method **does not exist today** — create it (see the full code in
03-domain.md). Then wire its call site: in `run_forever()`, after the
`_started` check and **before** `self._bot_loop.start(...)`, add:
```python
self.reconcile_on_startup()
```
It fetches `self._exchange.get_position(self._symbol)` (returns FLAT when no
position), reconstructs an open Trade via `TradeLedger.reconstruct_open` if
the exchange is non-flat but the DB has no open Trade, and records a
`ReconciliationRecord`. Mismatches are flagged, never auto-corrected.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_application/test_reconciliation_reconstructs_trade.py -q
```
- `test_exchange_long_no_db_trade_reconstructs`
- `test_exchange_flat_db_open_trade_kept`
- `test_mismatch_flagged_not_auto_corrected`

### Step 9: Dry-run fill synthesis (S10)
**File:** `finbot/core/application/use_cases/live_trading_runtime.py`

**Why this step is needed:** the `DryRunExchangeGateway.submit_order()`
returns `{"status":"dry_run"}` and emits no fill event; dry-run also builds
with `account=False`, so `AccountEventHandler` is never called. Without a
synthesized fill, no Trade would ever open in dry-run and the daily-loss gate
would never fire there — breaking dry-run/live parity (AGENTS.md).

Add a `_synthesize_fill(intent, intent_id)` helper and call it in the
DRY_RUN branch of `_dispatch_submission` (see 03-domain.md + ADR-8). The
fill uses the latest bar's close as the price; fill_id is derived from
intent_id for idempotency; side comes from `intent.side`. Live/testnet do
NOT synthesize — real fills arrive via the account stream.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_application/test_dry_run_order_simulation.py -q
```
- `test_dry_run_entry_opens_trade`
- `test_dry_run_exit_realizes_pnl`
- `test_dry_run_daily_loss_gate_blocks` (S10 + S5 combined)

### Step 10: Wire startup
**File:** `finbot/startup/service_factory.py`

Construct `TradeLedger(repo)` and inject into runtime + event handler.

**Verify:**
```bash
PYTHONPATH=. pytest tests/test_startup/test_service_factory.py -q
```

### Step 11: Slice 1 review gate
Run the four reviews (AGENTS.md §6) on the changed scope, then:
```bash
PYTHONPATH=. pytest tests -q
```
Particular attention: `/review_security` (atomicity around money),
`/review_logic` (PnL sign for short, fee handling), `/review_performance`
(the daily-loss query runs once per candle — confirm it uses the index and
isn't O(all trades)).

---

## Slice 2 — Should

### Step 12: Trade history query + summary (S11)
`list_closed_trades(bot_run_id=...)` newest-first; optional
`total_realized_pnl` helper. Surface via the existing status/history MCP tool.

### Step 13: End-to-end daily-loss test through MCP status (S12)
Confirm an operator querying `get_bot_status` after a losing trade sees the
gate would reject (or did reject) — closing the observability loop.

---

## Out of scope (tracked for later)

- Trailing stops (`max_favorable_price` column + update on each candle) —
  add as migration v4 when strategies support it.
- Unrealized PnL in the daily gate (needs a price source + cadence ADR).
- Signal-link enrichment (`entry_signal_key`, `stop_price`) — requires the
  order_id→intent_id (via cloid) lookup to be added to the repo.
