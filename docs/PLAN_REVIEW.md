# Integration Plan Review

This review checks `docs/INTEGRATION_PLAN.md` for missing steps, design gaps,
and live-trading risks. The overall direction is good: standalone Finbot,
copy only the Finbar strategy runtime subset, dry-run first, then replay,
websocket, testnet, and live.

The main gaps are not conceptual blockers, but they should be added before a
junior developer starts implementation.

---

## Summary verdict

The plan is sound, but it needs these additions:

1. Add a **Finbar runtime inventory/provenance phase** before copying code.
2. Add explicit **dependency declarations** for YAML/pandas/runtime packages.
3. Add a **bar source and warmup phase** before live websocket execution.
4. Add a **websocket runtime architecture phase**: reconnects, queues, shutdown,
   stale data, callback threading.
5. Add a **market constraints/rounding phase** before order planning.
6. Add a proper **order lifecycle state machine** before testnet execution.
7. Add stronger **secret handling and log redaction** tests.
8. Add **rate-limit/retry/backoff** rules for REST and websocket operations.
9. Add **observability/audit event standards** earlier, not as an afterthought.
10. Add **migration/schema-versioning** for SQLite persistence.

---

## Gap 1 — Copying Finbar runtime needs an inventory phase

### Issue

The plan says to copy the Finbar strategy runtime subset, but does not require a
module inventory before copying. A junior developer may copy too much or miss
hidden dependencies.

### Add before Phase 2

Create a new phase: **Phase 1.5 — Finbar runtime inventory and provenance**.

Tasks:

1. List every Finbar source file to copy.
2. For each file, document:
   - original path
   - target Finbot path
   - reason it is needed
   - known dependencies
   - whether it contains backtest-only logic
3. Create:

```text
docs/FINBAR_RUNTIME_COPY.md
```

4. Copy code only after this inventory is reviewed.
5. Keep copied modules small and avoid presentation/startup/repository code from
   Finbar unless specifically justified.

Tests/checks:

- `test_copied_runtime_modules_do_not_import_finbar`
- `test_copied_runtime_modules_do_not_import_finbar_presentation_or_startup`

---

## Gap 2 — Runtime dependencies are not declared yet

### Issue

`pyproject.toml` currently does not declare dependencies that will be needed soon:

- `PyYAML` for YAML parsing
- `pandas` for indicator/enrichment engine
- possibly `numpy`
- possibly `pandas-ta` or a copied indicator implementation alternative

The current venv may have these installed indirectly, but the package metadata
should be explicit.

### Add to Phase 3 / Phase 7

When implementing YAML loading:

```toml
"PyYAML>=6.0.0"
```

When implementing pandas indicator engine:

```toml
"pandas>=2.0.0"
"numpy>=1.26.0"
```

Only add `pandas-ta` if the copied runtime actually uses it.

Tests/checks:

- clean venv install succeeds
- `pip check` passes
- imports work without relying on transitive dependencies

---

## Gap 3 — Historical warmup is missing as its own phase

### Issue

Live strategies need warmup bars before the first websocket candle can be
evaluated. The current plan mentions warmup inside the indicator engine, but not
how bars are sourced.

### Add before Phase 12

Create: **Phase 10.5 — Historical bar source and warmup service**.

Tasks:

1. Add `BarSource` interface.
2. Add CSV replay source first.
3. Add Hyperliquid historical candle source later.
4. Add `WarmupWindow` service:
   - fixed max length
   - append closed bars
   - deduplicate by timestamp
   - sort by timestamp
   - detect gaps
5. Define warmup policy per strategy:
   - minimum bars required
   - max bars retained
   - behavior when insufficient bars

Tests:

- `test_warmup_window_sorts_bars_by_timestamp`
- `test_warmup_window_deduplicates_same_timestamp`
- `test_warmup_window_detects_time_gap`
- `test_strategy_does_not_evaluate_before_warmup_ready`
- `test_historical_source_returns_closed_bars_only`

---

## Gap 4 — Websocket architecture needs more detail

### Issue

Hyperliquid SDK websocket callbacks run outside the main bot control flow. The
plan does not yet define callback threading, queues, reconnect behavior, or
shutdown.

### Add to Phase 12

Tasks:

1. Use callbacks only to enqueue normalized events.
2. Process events in a controlled bot loop.
3. Define event types:
   - candle event
   - order update event
   - fill event
   - stale data event
   - shutdown event
4. Add reconnect/resubscribe behavior.
5. Add graceful shutdown:
   - stop websocket
   - flush pending events
   - persist final heartbeat/audit event
6. Add backpressure policy:
   - bounded queue
   - drop/replace old market updates if safe
   - never drop account/order/fill events silently

Tests:

- `test_websocket_callback_enqueues_event_without_strategy_execution`
- `test_event_loop_processes_events_in_timestamp_order_when_possible`
- `test_reconnect_resubscribes_to_candles`
- `test_shutdown_stops_websocket_and_flushes_events`
- `test_account_events_are_not_dropped_when_queue_is_full`

---

## Gap 5 — Candle close semantics must be explicit

### Issue

The plan says “closed candles only”, but needs an exact rule for Hyperliquid
messages.

### Add to Phase 12

Tasks:

1. Inspect Hyperliquid candle message fields.
2. Define how a candle is considered closed:
   - explicit closed flag if available, or
   - current exchange/server time greater than candle end time, or
   - next candle timestamp observed
3. Persist last processed candle timestamp per strategy/symbol/interval.
4. Never evaluate the same candle twice.

Tests:

- `test_partial_candle_update_is_not_processed`
- `test_candle_is_processed_when_next_candle_starts`
- `test_same_closed_candle_update_is_ignored_after_processing`
- `test_out_of_order_candle_does_not_trigger_duplicate_signal`

---

## Gap 6 — Market constraints and rounding are missing

### Issue

Before creating order intents, Finbot must know Hyperliquid size decimals, tick
precision, minimum order sizes, and slippage rules. Otherwise testnet orders may
fail or, worse, be rounded incorrectly.

### Add before Phase 13

Create: **Phase 12.5 — Market metadata and order normalization**.

Tasks:

1. Add `MarketMetadataProvider` interface.
2. Read asset metadata from Hyperliquid `Info`.
3. Store per-symbol metadata:
   - size decimals
   - price precision/tick rules
   - minimum size/notional if available
   - max leverage if available
4. Add `OrderNormalizer`:
   - round size down safely
   - round price to allowed precision
   - reject too-small orders
   - apply max slippage for market-as-IOC-limit orders

Tests:

- `test_order_size_is_rounded_down_to_size_decimals`
- `test_order_price_is_rounded_to_allowed_precision`
- `test_too_small_order_is_rejected`
- `test_market_order_uses_slippage_limited_ioc_price`
- `test_unknown_symbol_metadata_rejects_order_planning`

---

## Gap 7 — Order lifecycle state machine is missing

### Issue

The plan jumps from order intents to testnet execution. Live trading needs a
clear state machine for orders and fills, including partial fills and rejects.

### Add before/inside Phase 14

Create: **Phase 13.5 — Order lifecycle state machine**.

States:

```text
planned
risk_rejected
intent_persisted
submitted
accepted
open
partially_filled
filled
cancel_requested
cancelled
rejected
expired
unknown_reconcile_required
```

Tasks:

1. Add order lifecycle entity.
2. Add transition validator.
3. Map Hyperliquid responses/order updates/fills to transitions.
4. Make transitions idempotent.
5. Reconciliation can move stale/unknown states into
   `unknown_reconcile_required`.

Tests:

- `test_valid_order_state_transitions`
- `test_invalid_order_state_transition_is_rejected`
- `test_duplicate_fill_update_is_idempotent`
- `test_partial_fill_updates_remaining_size`
- `test_rejected_exchange_response_marks_order_rejected`
- `test_unknown_reconciliation_state_blocks_new_orders`

---

## Gap 8 — Secret handling and log redaction should be explicit

### Issue

The plan says no secrets in code, but it should require redaction and validation
tests.

### Add to Phase 15 and config phase

Tasks:

1. Add `SecretStr` or equivalent for private key settings.
2. Never print full private key/account secret values.
3. Add log redaction helper.
4. Reject live/testnet execution if private key is missing or malformed.
5. Keep dry-run free of private-key requirements.

Tests:

- `test_private_key_is_not_required_for_dry_run`
- `test_private_key_is_required_for_testnet_execution`
- `test_private_key_is_required_for_live_execution`
- `test_settings_repr_does_not_expose_private_key`
- `test_logs_redact_private_key_value`

---

## Gap 9 — Rate limits, retries, and backoff are missing

### Issue

Hyperliquid REST calls and websocket reconnects need defensive retry logic. This
should not be left to the SDK implicitly.

### Add to Phase 12/14

Tasks:

1. Add rate limiter for REST calls if SDK does not cover use case.
2. Add exponential backoff for reconnects and transient REST errors.
3. Define non-retryable errors:
   - invalid order
   - insufficient margin
   - bad signature
   - unknown symbol
4. Persist retry attempts for order submissions.
5. Never retry an order submission blindly without idempotent `cloid`.

Tests:

- `test_transient_rest_error_retries_with_backoff`
- `test_non_retryable_order_error_does_not_retry`
- `test_order_retry_requires_cloid`
- `test_websocket_reconnect_uses_backoff`

---

## Gap 10 — Persistence needs migrations/schema versioning

### Issue

SQLite tables will evolve. The plan mentions tables but not migrations or schema
versioning.

### Add to Phase 11

Tasks:

1. Add schema version table.
2. Add simple migration runner or choose Alembic.
3. Migrations must be idempotent.
4. App startup validates DB schema version.

Tests:

- `test_migrations_create_schema_from_empty_db`
- `test_migrations_are_idempotent`
- `test_startup_rejects_unsupported_schema_version`
- `test_repository_works_after_migration_runner`

---

## Gap 11 — Observability should be earlier

### Issue

A live bot must be explainable. Observability should start at dry-run/replay,
not be added after live mode.

### Add to Phase 10 onward

Standard event fields:

```text
bot_run_id
strategy_name
strategy_hash
symbol
interval
candle_timestamp
signal_key
order_intent_id
cloid
mode
risk_decision
reason
```

Tasks:

1. Add structured audit events.
2. Use consistent IDs across logs and DB records.
3. Add status command that reads from repository.

Tests:

- `test_signal_event_contains_correlation_fields`
- `test_order_intent_event_contains_cloid_when_available`
- `test_status_command_reports_last_signal_and_last_order`

---

## Gap 12 — “Full schema support” needs a compatibility matrix

### Issue

Saying “support full schema over time” can be misunderstood as “execute all
schema features live immediately.” The plan should require a matrix.

### Add to Phase 4

Create:

```text
docs/STRATEGY_COMPATIBILITY_MATRIX.md
```

Columns:

```text
Feature | Parsed | Validated | Replay | Live Dry-run | Testnet | Live | Notes
```

Rows:

- primary timeframe
- informative timeframe
- indicators by type
- features by type
- formulas
- long entry
- short entry
- long exit
- short exit
- crossovers
- ATR stop
- fixed stop
- risk/reward target
- explicit sizing
- multi-asset/portfolio

Tests/checks:

- compatibility CLI output should match matrix for supported/unsupported items

---

## Potential wrong-design risks

### Risk 1 — Copying too much Finbar

Copying the entire Finbar app would bring REST/MCP/backtest/storage complexity
into Finbot. The plan correctly says not to do that. The inventory phase should
enforce it.

### Risk 2 — Putting strategy evaluator in infrastructure

The current plan places `rule_based_strategy_evaluator.py` in infrastructure.
That is acceptable if it uses pandas/copied concrete services. However, the core
rule evaluation logic should be in domain/application services where possible.
A cleaner split:

```text
core/domain/services/condition_evaluator.py
core/domain/interfaces/risk_price_calculator.py
core/domain/interfaces/indicator_engine.py
infrastructure/strategy/rule_based_strategy_evaluator.py  # composition adapter
```

Do not let the evaluator become a god class.

### Risk 3 — Simulated replay position accounting too naive

Replay dry-run should be explicit that it is not a backtester. It can simulate
position state enough to avoid duplicate entries, but should not claim full PnL
accuracy unless it implements slippage, fees, funding, partial fills, and exits.

### Risk 4 — Storing private keys in DB/config files

Never store private keys in SQLite or bot config YAML. Secrets only from env or a
future secrets manager.

---

## Recommended changes to the main plan

Add these phases/checkpoints:

```text
Phase 1.5  Finbar runtime inventory and provenance
Phase 3.5  Explicit runtime dependency declaration
Phase 10.5 Historical bar source and warmup service
Phase 12.1 Websocket event loop, reconnect, shutdown design
Phase 12.2 Candle close semantics
Phase 12.5 Market metadata and order normalization
Phase 13.5 Order lifecycle state machine
Phase 14.5 Rate-limit/retry/backoff rules
```

And add these docs:

```text
docs/FINBAR_RUNTIME_COPY.md
docs/STRATEGY_COMPATIBILITY_MATRIX.md
docs/HYPERLIQUID_OPERATIONAL_MODEL.md
docs/SECURITY.md
```

---

## Revised immediate next steps

Before copying runtime code:

1. Add architecture/dependency tests.
2. Add target strategy fixtures.
3. Add `docs/FINBAR_RUNTIME_COPY.md` with a first inventory draft.
4. Add `docs/STRATEGY_COMPATIBILITY_MATRIX.md` with both AMT strategies marked
   as target support.
5. Add explicit `PyYAML` dependency when YAML loader work starts.
6. Only then start copying parser/domain code.
