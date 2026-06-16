# Finbot Integration Plan

This is the implementation plan for Finbot: a standalone live-trading runtime
that can execute strategies authored/backtested in Finbar.

The plan is intentionally phased so a junior developer can implement it in small,
reviewable steps without jumping directly to live trading.

---

## Core decisions

1. **Finbot is standalone at runtime**
   - No hardcoded local Finbar path.
   - No required Finbar package install.
   - No required Finbar REST/MCP service in production.

2. **First strategy targets**
   - `amt_dip_buyer_final.yaml`
   - `amt_v2_vol_filter.yaml`

3. **Schema goal**
   - Parse/validate the full known Finbar strategy file shape over time.
   - Live execution support is phased.
   - Unsupported live features must fail clearly.

4. **Copy only Finbar's strategy runtime subset**
   - Copy parser, validator, condition evaluator, risk calculator, indicator
     runtime, and AMT/profile math needed for live strategy evaluation.
   - Do **not** copy Finbar REST/MCP/backtest/optimization/storage app layers.
   - Rewrite copied imports from `finbar.*` to `finbot.*`.

5. **Execution rollout**
   - Validate locally.
   - Replay dry-run.
   - Hyperliquid websocket dry-run.
   - Hyperliquid testnet.
   - Live mode only after all safety gates exist.

---

## Definition of done for every phase

Before any phase is considered complete:

```bash
ruff check finbot tests
black --check finbot tests
pytest tests
```

All new code must follow `AGENTS.md`:

- one class per file
- constructor dependency injection
- no Finbar imports in production code
- Hyperliquid SDK imports only in infrastructure
- domain/application layers do not import infrastructure
- secrets never logged or persisted

---

## Target architecture

```text
finbot/
  core/
    domain/
      entities/          # pure dataclasses/value objects/enums
      interfaces/        # ABC/Protocol boundaries
      services/          # pure domain services/math
    application/
      dto/               # use-case request/result DTOs
      use_cases/         # orchestration, domain interfaces only
      services/          # app-level orchestration
  infrastructure/
    strategy/            # YAML loader, pandas engine, copied runtime impls
    adapters/            # Hyperliquid, dry-run gateway, market streams
    repositories/        # SQLite implementations
  presentation/
    cli/                 # validate, compat, replay, run, panic, status
  startup/               # composition root/factories
```

---

# Phase 0 — Dependency hygiene and architecture guardrails

## Goal

Keep Finbot standalone and enforce Clean Architecture boundaries.

## Tasks

1. Confirm `pyproject.toml` has no Finbar dependency.
2. Confirm no `.pth` path workaround is required.
3. Add architecture tests:

```text
tests/test_architecture/test_dependency_rules.py
```

The tests should fail if:

- `finbot/core/domain` imports `finbar`, `hyperliquid`, `sqlalchemy`, `fastapi`,
  `pydantic_settings`, or `finbot.infrastructure`.
- `finbot/core/application` imports `finbar`, `hyperliquid`, `sqlalchemy`,
  `fastapi`, or `finbot.infrastructure`.
- any production code imports `finbar`.

## Required tests

- `test_domain_layer_has_no_forbidden_imports`
- `test_application_layer_has_no_forbidden_imports`
- `test_production_code_does_not_import_finbar`

## Acceptance criteria

- Tests pass without Finbar installed.
- Production code does not import Finbar.

---

# Phase 1 — Strategy fixtures and acceptance targets

## Goal

Bring the two target strategies into Finbot as fixtures.

## Tasks

1. Create:

```text
tests/fixtures/strategies/amt_dip_buyer_final.yaml
tests/fixtures/strategies/amt_v2_vol_filter.yaml
tests/fixtures/strategies/strategy_requirements.json
```

2. Copy the two YAML files exactly from Finbar.
3. Document each strategy's required indicators/operators/risk types.

## Required tests

```text
tests/test_infrastructure/test_strategy_fixtures.py
```

- `test_target_strategy_files_exist`
- `test_target_strategy_files_are_valid_yaml`
- `test_target_strategy_names_match_expected`
- `test_target_strategy_requirements_are_documented`

## Acceptance criteria

- Both strategy fixtures parse as YAML.
- Strategy names match expected values.

---

# Phase 1.5 — Finbar runtime inventory and provenance

## Goal

Avoid copying too much Finbar and document exactly what is copied.

## Tasks

1. Create:

```text
docs/FINBAR_RUNTIME_COPY.md
```

2. Inventory every Finbar file proposed for copying.
3. For each file document:
   - original Finbar path
   - target Finbot path
   - why it is needed
   - dependencies
   - whether it contains backtest-only logic
4. Review inventory before copying code.
5. Do not copy Finbar presentation/startup/repository/backtest-result modules
   unless explicitly justified.

## Required tests/checks

- `test_copied_runtime_modules_do_not_import_finbar`
- `test_copied_runtime_modules_do_not_import_finbar_presentation_or_startup`

## Acceptance criteria

- Runtime copy inventory exists.
- Copy scope is explicitly reviewed.

---

# Phase 2 — Strategy domain entities

## Goal

Create Finbot-owned strategy model objects compatible with Finbar YAML shape.

## Tasks

Create one class per file under `finbot/core/domain/entities/`:

```text
strategy_definition.py
strategy_parameter.py
timeframe_declaration.py
informative_timeframe.py
indicator_spec.py
feature_spec.py
side_rules.py
risk_spec.py
condition.py
condition_group.py
operand.py
formula_node.py
strategy_validation_error.py
strategy_validation_result.py
```

Rules:

- Use dataclasses/enums.
- No YAML, pandas, Pydantic, Hyperliquid, SQLAlchemy, or Finbar imports.
- Keep names/fields close to Finbar where sensible.
- No ORM/database fields.

## Required tests

```text
tests/test_domain/test_strategy_entities.py
```

- `test_strategy_definition_can_be_constructed`
- `test_strategy_parameter_has_default_value`
- `test_condition_group_supports_all_any_not_shapes`
- `test_strategy_validation_result_reports_valid_when_no_errors`
- `test_strategy_validation_result_reports_invalid_when_errors_exist`

## Acceptance criteria

- Pure domain entities exist.
- Architecture tests still pass.

---

# Phase 3 — YAML/JSON strategy loader

## Goal

Load Finbar-style YAML/JSON into Finbot domain entities.

## Dependency update

Add explicit dependency when this phase starts:

```toml
"PyYAML>=6.0.0"
```

## Tasks

1. Add interface:

```text
finbot/core/domain/interfaces/strategy_definition_loader.py
```

Methods:

```python
def load_from_text(self, content: str) -> StrategyDefinition: ...
def load_from_file(self, path: str) -> StrategyDefinition: ...
```

2. Add implementation:

```text
finbot/infrastructure/strategy/yaml_strategy_definition_loader.py
```

3. Support YAML and JSON.
4. Resolve parameter defaults.
5. Preserve name, description, timeframe declarations, indicators, features,
   side rules, and risk blocks.
6. Return clear errors for missing files and invalid YAML/JSON.

## Required tests

```text
tests/test_infrastructure/test_yaml_strategy_definition_loader.py
```

- `test_load_amt_dip_buyer_final`
- `test_load_amt_v2_vol_filter`
- `test_load_strategy_parameters`
- `test_load_primary_timeframe`
- `test_load_indicators_in_order`
- `test_load_long_entry_and_exit_conditions`
- `test_load_risk_block`
- `test_missing_file_returns_clear_error`
- `test_invalid_yaml_returns_clear_error`

## Acceptance criteria

- Both target strategy fixtures load into `StrategyDefinition`.

---

# Phase 3.5 — Explicit runtime dependency declaration

## Goal

Avoid relying on transitive dependencies or whatever happens to be installed in a
local venv.

## Tasks

1. Add dependencies only when their phase needs them.
2. Expected future dependencies:

```toml
"PyYAML>=6.0.0"        # strategy loader
"pandas>=2.0.0"        # indicator engine
"numpy>=1.26.0"        # indicator/profile math
```

3. Add `pandas-ta` only if the copied runtime actually uses it.
4. Run install in a clean venv when dependency set changes.

## Required checks

- `pip check`
- clean venv install
- tests import the new modules without relying on transitive packages

---

# Phase 4 — Strategy validator and compatibility matrix

## Goal

Validate strategies and report whether each feature is supported for live
execution.

## Tasks

1. Add interface:

```text
finbot/core/domain/interfaces/strategy_validator.py
```

2. Add use case:

```text
finbot/core/application/use_cases/validate_strategy_definition.py
```

3. Add DTOs:

```text
validate_strategy_request.py
validate_strategy_result.py
strategy_compatibility_result.py
```

4. Add docs matrix:

```text
docs/STRATEGY_COMPATIBILITY_MATRIX.md
```

Columns:

```text
Feature | Parsed | Validated | Replay | Live Dry-run | Testnet | Live | Notes
```

5. Add CLI commands:

```bash
finbot validate-strategy --strategy path.yaml
finbot strategy-compat --strategy path.yaml
```

6. MVP validation rules:
   - schema version exists
   - strategy name exists
   - primary timeframe exists
   - indicators have name/type/timeframe
   - at least one side has entry rules
   - live mode requires stop loss
   - unknown operators are errors
   - unknown indicators are compatibility errors
   - unsupported live features are explicit errors for run/testnet/live

## Required tests

```text
tests/test_application/test_validate_strategy_definition.py
tests/test_presentation/test_validate_strategy_cli.py
```

- `test_validate_target_strategies_success`
- `test_missing_schema_version_is_error`
- `test_missing_primary_timeframe_is_error`
- `test_unknown_operator_is_error`
- `test_unknown_indicator_is_compatibility_error`
- `test_live_mode_missing_stop_is_error`
- `test_dry_run_missing_stop_is_warning`
- `test_compatibility_output_matches_matrix_for_target_strategies`
- `test_cli_validate_strategy_success_exit_code_zero`
- `test_cli_validate_strategy_failure_exit_code_nonzero`

## Acceptance criteria

- Both target strategies validate.
- Compatibility command clearly reports unsupported features.

---

# Phase 5 — Condition evaluator

## Goal

Evaluate entry/exit condition trees on enriched bars.

## Tasks

1. Add:

```text
finbot/core/domain/services/condition_evaluator.py
```

2. Implement groups:
   - `all`
   - `any`
   - `not`

3. Implement operators:
   - required first: `is_true`, `<`
   - also: `is_false`, `>`, `>=`, `<=`, `==`, `!=`
   - stateful: `crosses_above`, `crosses_below`

4. Resolve operands from:
   - bar fields
   - literals
   - params

5. Maintain previous values for crossovers.

## Required tests

```text
tests/test_domain/test_condition_evaluator.py
```

- `test_is_true_operator`
- `test_less_than_operator`
- `test_all_group_requires_all_true`
- `test_any_group_requires_one_true`
- `test_not_group_inverts_result`
- `test_missing_bar_field_returns_clear_error`
- `test_crosses_above_requires_previous_value`
- `test_crosses_below_requires_previous_value`
- `test_previous_values_are_committed_after_evaluation`

## Acceptance criteria

- Conditions from both target strategies evaluate correctly on synthetic enriched
  bars.

---

# Phase 6 — Risk price calculator

## Goal

Calculate stop/target prices from strategy risk specs.

## Tasks

1. Add interface:

```text
finbot/core/domain/interfaces/risk_price_calculator.py
```

2. Add implementation:

```text
finbot/infrastructure/strategy/json_risk_price_calculator.py
```

3. Support:
   - ATR stop loss
   - fixed percent stop loss if in schema
   - risk/reward take profit
   - parameter references like `{{ atr_stop_mult }}`

4. Prefer `Decimal` for domain-level money/risk values.

## Required tests

```text
tests/test_infrastructure/test_json_risk_price_calculator.py
```

- `test_long_atr_stop_loss`
- `test_short_atr_stop_loss`
- `test_risk_reward_take_profit_for_long`
- `test_risk_reward_take_profit_for_short`
- `test_parameter_reference_multiplier_is_resolved`
- `test_missing_atr_field_returns_clear_error`
- `test_unsupported_risk_type_returns_clear_error`

## Acceptance criteria

- Target strategies produce expected stop/target prices from synthetic bars.

---

# Phase 7 — Indicator and AMT/profile runtime

## Goal

Compute enriched bars required by the target AMT strategies.

## Dependency update

Add when implementation starts:

```toml
"pandas>=2.0.0"
"numpy>=1.26.0"
```

## Tasks

1. Add interface:

```text
finbot/core/domain/interfaces/indicator_engine.py
```

2. Add implementation:

```text
finbot/infrastructure/strategy/pandas_indicator_engine.py
```

3. Copy/adapt Finbar math for:
   - ATR
   - volume profile
   - `vp_vah`
   - `vp_val`
   - `above_value`
   - `acceptance_into_value`
   - `value_area_width_pct`

4. Internal bar format:

```text
timestamp, open, high, low, close, volume
```

5. Engine accepts a recent bar window and returns enriched bars.

## Required tests

```text
tests/test_infrastructure/test_pandas_indicator_engine.py
tests/fixtures/bars/amt_sample_bars.csv
```

- `test_atr_column_is_added`
- `test_volume_profile_columns_are_added`
- `test_above_value_is_boolean`
- `test_acceptance_into_value_is_boolean`
- `test_value_area_width_pct_is_added_for_v2`
- `test_indicator_engine_returns_latest_enriched_bar`
- `test_empty_bars_returns_clear_error`
- `test_not_enough_warmup_bars_returns_warning_or_error`

## Acceptance criteria

- Enriched latest bar contains all fields needed by both target strategies.

---

# Phase 8 — Native rule-based strategy evaluator

## Goal

Turn enriched bars and current position into normalized live signals.

## Tasks

1. Add:

```text
finbot/infrastructure/strategy/rule_based_strategy_evaluator.py
```

2. It implements:

```text
finbot/core/domain/interfaces/strategy_evaluator.py
```

3. Behavior:
   - if flat: evaluate entries
   - if long: evaluate long exit
   - if short: evaluate short exit
   - calculate stop/target on entry
   - preserve crossover state
   - expose `reset()` for replay/bot restart

4. Keep pure condition/risk logic outside this class. Do not make it a god
   class.

## Required tests

```text
tests/test_infrastructure/test_rule_based_strategy_evaluator.py
```

- `test_hold_when_no_entry_condition_true`
- `test_long_entry_when_acceptance_into_value_true`
- `test_v2_entry_requires_value_area_width_filter`
- `test_long_exit_when_above_value_true`
- `test_entry_signal_includes_stop_and_target`
- `test_existing_long_position_does_not_open_new_long`
- `test_evaluator_state_resets_between_replays`

## Acceptance criteria

- Both target strategies produce hold/entry/exit signals from synthetic enriched
  bars.

---

# Phase 9 — Optional parity tests against Finbar

## Goal

Detect drift from Finbar without making Finbar a runtime dependency.

## Tasks

1. Add pytest marker:

```toml
markers = [
  "finbar_parity: optional tests comparing Finbot runtime against Finbar",
]
```

2. Create:

```text
tests/test_parity/test_finbar_strategy_parity.py
```

3. Skip unless `FINBOT_FINBAR_PARITY_PATH` is set.
4. If set, add that path to `sys.path` inside the test only.
5. Compare selected outputs between Finbar and Finbot.

## Required tests

- `test_parity_tests_skip_without_env_var`
- `test_parse_target_strategy_matches_finbar_name_and_requirements`
- `test_condition_signal_matches_finbar_on_synthetic_enriched_bars`
- `test_risk_stop_target_matches_finbar_on_synthetic_bar`
- `test_indicator_columns_match_finbar_on_fixture_bars`

## Acceptance criteria

- Normal tests require no Finbar.
- Optional parity tests can be run by developers with a Finbar checkout.

---

# Phase 10 — Replay dry-run engine

## Goal

Run complete strategy pipeline over historical bars without network or exchange
access.

## Tasks

1. Add DTOs:

```text
replay_strategy_request.py
replay_strategy_result.py
signal_event.py
```

2. Add use case:

```text
finbot/core/application/use_cases/replay_strategy.py
```

3. Add CSV bar loader in infrastructure.
4. Replay each closed bar:
   - append to warmup window
   - enrich latest window
   - evaluate strategy
   - create signal key
   - prevent duplicate processing
   - update simulated position state
   - record signal event

5. Add CLI:

```bash
finbot replay --strategy path.yaml --bars path.csv --symbol BTC --interval 1h
```

6. Be explicit: replay is **not a full backtester** unless fees/slippage/funding
   and fill modeling are implemented.

## Required tests

```text
tests/test_application/test_replay_strategy.py
tests/test_presentation/test_replay_cli.py
```

- `test_replay_runs_without_exchange_gateway`
- `test_replay_produces_signal_events`
- `test_replay_uses_closed_bars_only`
- `test_replay_prevents_duplicate_signal_keys`
- `test_replay_reports_indicator_warmup_errors`
- `test_replay_cli_success_exit_code_zero`
- `test_replay_cli_missing_file_exit_code_nonzero`

## Acceptance criteria

- Replay dry-run is deterministic and requires no secrets/network.

---

# Phase 10.5 — Historical bar source and warmup service

## Goal

Make warmup explicit before websocket/live operation.

## Tasks

1. Add `BarSource` interface.
2. Add CSV source first.
3. Add Hyperliquid historical candle source later.
4. Add `WarmupWindow` service:
   - fixed max length
   - append closed bars
   - deduplicate timestamp
   - sort timestamp
   - detect interval gaps
5. Define per-strategy warmup readiness.
6. Do not evaluate a strategy until warmup is ready.

## Required tests

- `test_warmup_window_sorts_bars_by_timestamp`
- `test_warmup_window_deduplicates_same_timestamp`
- `test_warmup_window_detects_time_gap`
- `test_strategy_does_not_evaluate_before_warmup_ready`
- `test_historical_source_returns_closed_bars_only`

## Acceptance criteria

- Live/replay engines share the same warmup behavior.

---

# Phase 11 — Bot state persistence and migrations

## Goal

Persist enough state to survive restart and prevent duplicate orders.

## Tasks

1. Define repository interfaces before SQL implementations.
2. Add SQLite tables for:
   - bot runs
   - strategy snapshots/hashes
   - processed signal keys
   - order intents
   - order responses
   - fills
   - reconciliations
   - risk events
   - audit log
3. Add schema version table.
4. Add idempotent migration runner or Alembic.
5. Startup validates DB schema version.
6. Signal key persistence must be idempotent.

## Required tests

```text
tests/test_infrastructure/test_sql_bot_state_repository.py
tests/test_infrastructure/test_database_migrations.py
```

- `test_migrations_create_schema_from_empty_db`
- `test_migrations_are_idempotent`
- `test_startup_rejects_unsupported_schema_version`
- `test_create_bot_run`
- `test_store_strategy_snapshot_hash`
- `test_processed_signal_key_is_idempotent`
- `test_order_intent_is_saved_before_response`
- `test_order_response_is_saved_after_intent`
- `test_repository_survives_new_session_restart`

## Acceptance criteria

- Restart simulation proves duplicate signal keys remain blocked.

---

# Phase 11.5 — Observability and audit event standard

## Goal

Make bot behavior explainable from replay onward.

## Tasks

1. Standardize event fields:

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

2. Add structured audit event entity.
3. Persist audit events.
4. Add status command reading from repository.

## Required tests

- `test_signal_event_contains_correlation_fields`
- `test_order_intent_event_contains_cloid_when_available`
- `test_status_command_reports_last_signal_and_last_order`

## Acceptance criteria

- Replay and dry-run decisions are traceable.

---

# Phase 12 — Hyperliquid read-only dry-run

## Goal

Connect to Hyperliquid market data without placing orders.

## Secrets required

- Public market data: no secrets.
- Optional account read-only streams: wallet/account address only.
- No private key in this phase.

## Tasks

1. Add:

```text
finbot/infrastructure/adapters/hyperliquid_market_data_stream.py
```

2. Use SDK `Info(..., skip_ws=False)`.
3. Subscribe to candles:

```python
{"type": "candle", "coin": symbol, "interval": interval}
```

4. Convert SDK messages to Finbot bar events.
5. Only process closed candles.
6. Add stale-data timeout.
7. Add read-only dry-run command:

```bash
finbot run --config bot.yaml --dry-run
```

## Required tests

Use fakes/mocks. Normal tests must not hit real Hyperliquid.

- `test_subscribe_candles_uses_expected_subscription_shape`
- `test_candle_message_maps_to_bar_event`
- `test_partial_candle_is_ignored`
- `test_closed_candle_is_processed`
- `test_stale_data_triggers_risk_event`
- `test_dry_run_loop_never_calls_exchange_submit_order`

## Acceptance criteria

- Websocket dry-run produces signals/order intents without private key.

---

# Phase 12.1 — Websocket event loop, reconnect, and shutdown

## Goal

Keep SDK callbacks out of strategy/execution logic.

## Tasks

1. SDK callbacks only enqueue normalized events.
2. Bot event loop processes queued events.
3. Define event types:
   - candle
   - order update
   - fill
   - stale data
   - shutdown
4. Add reconnect/resubscribe behavior with backoff.
5. Add graceful shutdown:
   - stop websocket
   - flush queue
   - persist final heartbeat/audit event
6. Add bounded queue/backpressure policy.
7. Never silently drop account/order/fill events.

## Required tests

- `test_websocket_callback_enqueues_event_without_strategy_execution`
- `test_reconnect_resubscribes_to_candles`
- `test_shutdown_stops_websocket_and_flushes_events`
- `test_account_events_are_not_dropped_when_queue_is_full`

## Acceptance criteria

- Websocket callbacks are isolated from trading decisions.

---

# Phase 12.2 — Candle close semantics

## Goal

Define exactly when a Hyperliquid candle is safe to process.

## Tasks

1. Inspect Hyperliquid candle message fields.
2. Decide closed candle rule:
   - explicit closed flag if available, or
   - server time > candle end time, or
   - next candle timestamp observed.
3. Persist last processed candle timestamp per strategy/symbol/interval.
4. Ignore duplicate/out-of-order closed candle updates.

## Required tests

- `test_partial_candle_update_is_not_processed`
- `test_candle_is_processed_when_next_candle_starts`
- `test_same_closed_candle_update_is_ignored_after_processing`
- `test_out_of_order_candle_does_not_trigger_duplicate_signal`

## Acceptance criteria

- Strategy never evaluates a partially forming candle by default.

---

# Phase 12.5 — Market metadata and order normalization

## Goal

Prepare order sizes/prices that Hyperliquid will accept.

## Tasks

1. Add `MarketMetadataProvider` interface.
2. Read Hyperliquid metadata via `Info`.
3. Store per-symbol:
   - size decimals
   - price precision/tick rules
   - min size/notional if available
   - max leverage if available
4. Add `OrderNormalizer`:
   - round size down safely
   - round price to allowed precision
   - reject too-small orders
   - apply max slippage for market-as-IOC-limit orders

## Required tests

- `test_order_size_is_rounded_down_to_size_decimals`
- `test_order_price_is_rounded_to_allowed_precision`
- `test_too_small_order_is_rejected`
- `test_market_order_uses_slippage_limited_ioc_price`
- `test_unknown_symbol_metadata_rejects_order_planning`

## Acceptance criteria

- Order planner cannot produce invalid precision/size orders.

---

# Phase 13 — Order planning and risk gates

## Goal

Convert signals into safe order intents before exchange submission.

## Tasks

1. Add `OrderPlanner`.
2. Add position sizing policy.
3. Add risk gate chain:
   - mode gate
   - duplicate signal gate
   - stale data gate
   - max position notional gate
   - max open orders gate
   - max leverage gate
   - max daily loss gate
   - reduce-only exit gate
4. Dry-run output includes accepted/rejected, reason, proposed order intent, and
   signal key.

## Required tests

- `test_buy_signal_creates_long_entry_intent`
- `test_exit_signal_creates_reduce_only_intent`
- `test_duplicate_signal_is_rejected`
- `test_stale_data_is_rejected`
- `test_oversized_position_is_rejected`
- `test_max_open_orders_is_enforced`
- `test_daily_loss_limit_is_enforced`
- `test_dry_run_order_intent_is_persisted_but_not_submitted`

## Acceptance criteria

- Dry-run emits auditable order intents and risk decisions.

---

# Phase 13.5 — Order lifecycle state machine

## Goal

Track orders through submits, fills, cancels, rejects, and reconciliation.

## States

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

## Tasks

1. Add order lifecycle entity.
2. Add transition validator.
3. Map exchange responses/order updates/fills to transitions.
4. Make duplicate updates idempotent.
5. Reconciliation can move unsafe states to `unknown_reconcile_required`.
6. Block new orders when an existing order is unknown/unreconciled.

## Required tests

- `test_valid_order_state_transitions`
- `test_invalid_order_state_transition_is_rejected`
- `test_duplicate_fill_update_is_idempotent`
- `test_partial_fill_updates_remaining_size`
- `test_rejected_exchange_response_marks_order_rejected`
- `test_unknown_reconciliation_state_blocks_new_orders`

## Acceptance criteria

- Order state is explicit and restart-safe.

---

# Phase 14 — Hyperliquid testnet execution

## Goal

Place, monitor, cancel, and reconcile testnet orders.

## Secrets required

- Agent Wallet private key (testnet) — generated at the testnet API page.
- Main account address (the wallet whose margin is traded).
- Never use your main wallet's private key; always use a dedicated Agent Wallet.

## Tasks

1. Complete:

```text
finbot/infrastructure/adapters/hyperliquid_exchange_gateway.py
```

2. Use SDK `Exchange` for:
   - market open
   - market close
   - limit order
   - cancel
   - cancel by cloid
   - modify order later if needed
3. Use `cloid` for idempotency.
4. Implement REST reconciliation:
   - user state
   - open orders
   - fills
5. Implement account websocket subscriptions:
   - `userFills`
   - `orderUpdates`
   - optionally `webData2`
6. Add panic commands:

```bash
finbot panic --symbol BTC --cancel-orders
finbot panic --symbol BTC --cancel-orders --close-position
```

## Required tests

Normal tests use fake SDK clients.

- `test_market_entry_maps_to_sdk_market_open`
- `test_exit_order_is_reduce_only`
- `test_cancel_by_cloid_maps_to_sdk`
- `test_exchange_response_is_persisted`
- `test_reconciliation_detects_unknown_open_order`
- `test_reconciliation_detects_position_mismatch`
- `test_panic_cancel_orders_calls_cancel_all`
- `test_panic_close_position_requires_explicit_flag`

Optional marked tests:

- `testnet_place_tiny_order`
- `testnet_cancel_open_order`
- `testnet_close_position`

## Acceptance criteria

- Testnet bot can place/cancel tiny orders and reconcile after restart.

---

# Phase 14.5 — Rate limits, retries, and backoff

## Goal

Avoid unsafe repeated REST/order operations.

## Tasks

1. Add rate limiter for REST calls if SDK behavior is insufficient.
2. Add exponential backoff for reconnects/transient REST errors.
3. Define non-retryable errors:
   - invalid order
   - insufficient margin
   - bad signature
   - unknown symbol
4. Persist retry attempts for order submissions.
5. Never retry order submission blindly without idempotent `cloid`.

## Required tests

- `test_transient_rest_error_retries_with_backoff`
- `test_non_retryable_order_error_does_not_retry`
- `test_order_retry_requires_cloid`
- `test_websocket_reconnect_uses_backoff`

## Acceptance criteria

- Retry behavior is deterministic and safe.

---

# Phase 15 — Security and secret handling

## Goal

Ensure secrets are never required for dry-run and never leaked.

## Tasks

1. Create:

```text
docs/SECURITY.md
```

2. Use secret-safe settings for private keys.
3. Never print/log full private keys.
4. Add log redaction helper.
5. Reject testnet/live execution if private key missing or malformed.
6. Never store private keys in DB or bot config YAML.
7. Keep fund transfers/withdrawals out of MVP.

## Required tests

- `test_private_key_is_not_required_for_dry_run`
- `test_private_key_is_required_for_testnet_execution`
- `test_private_key_is_required_for_live_execution`
- `test_settings_repr_does_not_expose_private_key`
- `test_logs_redact_private_key_value`
- `test_fund_transfer_methods_are_not_available`

## Acceptance criteria

- Dry-run requires no secrets.
- Secrets are redacted and never persisted.

---

# Phase 16 — Live mode unlock

## Goal

Enable live trading only after all safety requirements are implemented.

## Required before live

- replay dry-run works
- websocket dry-run works
- testnet execution works
- duplicate prevention works
- restart reconciliation works
- kill switch works
- stale data protection works
- max loss/risk gates work
- explicit live acknowledgment works
- DB persistence/migrations work
- secret redaction works

## Tasks

1. Require:

```env
FINBOT_MODE=live
FINBOT_LIVE_TRADING_ACK=true
```

2. Require Agent Wallet private key and main account address.
3. Require max notional config.
4. Require DB persistence enabled.
5. Require startup reconciliation before first signal.
6. Refuse withdrawals/transfers.
7. Start with tiny max notional.

## Required tests

```text
tests/test_application/test_live_mode_safety.py
```

- `test_live_mode_without_ack_is_rejected`
- `test_live_mode_without_private_key_is_rejected`
- `test_live_mode_without_reconciliation_is_rejected`
- `test_live_mode_without_persistence_is_rejected`
- `test_live_mode_requires_max_position_limit`

## Acceptance criteria

- Live mode cannot accidentally start.

---

# Hyperliquid operational model

Create/maintain:

```text
docs/HYPERLIQUID_OPERATIONAL_MODEL.md
```

## Public market data

No secrets required.

```python
{"type": "candle", "coin": "BTC", "interval": "1h"}
{"type": "bbo", "coin": "BTC"}
{"type": "trades", "coin": "BTC"}
```

## Account read-only data

Requires public wallet/account address, not private key.

```python
{"type": "userFills", "user": address}
{"type": "orderUpdates", "user": address}
{"type": "webData2", "user": address}
```

## Order execution

Hyperliquid uses Agent Wallet (API Wallet) signatures, not traditional CEX API
keys. An Agent Wallet is a dedicated private key authorized to sign trades on
behalf of your main account — it cannot withdraw funds. Always use an Agent
Wallet; never put your main wallet's private key in the bot configuration.

> ⚠️ Agent keys expire after 90 days (or 180 if set to MAX). Regenerate on the
> API page when the bot gets unauthorized errors.

Finbot should not manage deposits, withdrawals, bridging, or transfers in MVP.
It should only trade already-deposited Hyperliquid collateral.

---

# Final implementation checklist

Proceed in this order:

1. Phase 0 architecture tests.
2. Phase 1 strategy fixtures.
3. Phase 1.5 Finbar runtime copy inventory.
4. Phase 2 strategy entities.
5. Phase 3 loader.
6. Phase 4 validator + compatibility matrix/CLI.
7. Phase 5 condition evaluator.
8. Phase 6 risk calculator.
9. Phase 7 indicator engine.
10. Phase 8 rule-based evaluator.
11. Phase 9 optional parity tests.
12. Phase 10 replay dry-run.
13. Phase 10.5 warmup/bar source.
14. Phase 11 persistence/migrations.
15. Phase 11.5 observability/audit events.
16. Phase 12 websocket dry-run.
17. Phase 12.1 event loop/reconnect/shutdown.
18. Phase 12.2 candle close semantics.
19. Phase 12.5 market metadata/order normalization.
20. Phase 13 order planning/risk gates.
21. Phase 13.5 order lifecycle state machine.
22. Phase 14 testnet execution.
23. Phase 14.5 retry/backoff.
24. Phase 15 security.
25. Phase 16 live unlock.

Do not implement testnet/live order submission before replay dry-run,
persistence, risk gates, order lifecycle, and kill-switch behavior exist.
