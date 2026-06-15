# Domain Model — Import Shared Strategy Runtime Package

## The core decision: adopt the package's strategy domain model

Finbot **deletes its copied strategy domain entities and uses the package's
directly.** The package's `domain/entities/` and `domain/interfaces/`
subpackages are pure (verified: no numpy/pandas/framework imports in entities;
interfaces are ABCs). A pure external domain library is a legitimate domain-layer
dependency, exactly like `decimal` or `dataclasses`.

This eliminates entity duplication and drift — the whole point of the package.

### Package strategy entities Finbot adopts (used directly, NOT redefined)

Imported from `finbar_strategy_runtime.domain.entities`:

| Entity | Used by Finbot for |
|--------|--------------------|
| `StrategyDefinition` | The canonical parsed strategy, returned by the loader, passed to the evaluator factory |
| `StrategyValidationResult` | Startup validation; source of `required_columns` |
| `StrategyValidationError` | Validation error reporting |
| `Condition`, `ConditionGroup`, `Operand` | Strategy rule trees (used inside the package; Finbot rarely touches directly) |
| `SideRules` | Per-side entry/exit trees on a `StrategyDefinition` |
| `RiskSpec` | Stop/target spec on a `StrategyDefinition` |
| `IndicatorSpec`, `FeatureSpec`, `FormulaNode` | Indicator/feature declarations |
| `TimeframeDeclaration`, `InformativeTimeframe` | Multi-timeframe declarations |
| `StrategyParameter`, `StrategyMeta`, `StrategyKind` | Metadata |
| `SignalResult` | The package's pre-adapter signal output — mapped to `SignalDecision` in the adapter |
| `DataMode` | Used by `StrategyMeta` |

### Package interfaces Finbot adopts

Imported from `finbar_strategy_runtime.domain.interfaces`:

| Interface | Finbot use |
|-----------|------------|
| `TradingStrategy` | The package strategy contract (`on_bar(bar, position) -> SignalResult`). The evaluator adapter wraps one instance. |
| `StrategyDefinitionParser` | The loader delegates to the package `StrategyDefinitionParser` (concrete, in `parser/`). |
| `IndicatorCalculator` | The package `PandasTaIndicatorCalculator` (concrete, in `indicators/`) implements it. |

> These package interfaces are NOT the same as Finbot's own
> `finbot/core/domain/interfaces/strategy_evaluator.py` etc. Finbot keeps its
> own `StrategyEvaluator` / `StrategyEvaluatorFactory` /
> `StrategyDefinitionLoader` / `IndicatorCalculator` interfaces because their
> contracts are Finbot-shaped (e.g. `evaluate` returns a `SignalDecision` with
> live idempotency fields; `load_from_file` raises `StrategyLoadError`). The
> concrete adapters in `infrastructure/` bridge Finbot's interfaces to the
> package. See the adapter table below.

### Finbot-owned entities (NOT in the package — unchanged)

| Entity | Fields | Behaviour | Persisted? |
|--------|--------|-----------|------------|
| `SignalDecision` | action, symbol, interval, candle_timestamp, strategy_hash, confidence, stop_price, target_price | Bot-safe signal with a unique `signal_key` for idempotency | Yes |
| `SignalAction` | enum: hold/long_entry/short_entry/long_exit/short_exit | Finbot's live action vocabulary | Yes |
| `PositionSnapshot`, `PositionDirection` | symbol, direction, size, entry_price, unrealized_pnl | Finbot live position state | Yes |
| `OrderIntent` | symbol, side, size, order_type, reduce_only, cloid, signal_key, prices | Planned order | Yes |
| `RiskDecision` / `EnrichmentValidationResult` / `CandleProcessingResult` | see existing files | Finbot runtime outputs | Yes |
| `StrategyLoadError` | message | Finbot's loader error type | n/a |

These stay in `finbot/core/domain/entities/` because they carry live-trading
concerns (idempotency keys, exchange fields) the package does not have.

### Value Objects

| Name | Fields | Used where |
|------|--------|------------|
| `SignalKey` | strategy_hash, symbol, interval, candle_timestamp | Duplicate prevention — Finbot-owned (`SignalDecision.signal_key` property) |
| `StrategySchemaVersion` | e.g. `"2.0"` | Compatibility check; comes from the definition, NOT inferred from package semver |
| `RuntimePackageVersion` | e.g. `"0.1.0"` | Audit/diagnostics only (`finbar_strategy_runtime.__version__`) |

---

## Adapter boundary — precise contract

Finbot keeps four thin adapters in `finbot/infrastructure/`. Each bridges a
**Finbot** interface to the **package**.

| Finbot interface (domain) | Finbot adapter (infrastructure) | Delegates to (package) |
|---------------------------|---------------------------------|------------------------|
| `StrategyDefinitionLoader` | `YamlStrategyDefinitionLoader` (kept, re-pointed) | `finbar_strategy_runtime.parser.StrategyDefinitionParser` |
| `StrategyEvaluatorFactory` | `SharedRuntimeStrategyEvaluatorFactory` (new) | `finbar_strategy_runtime.evaluation.StrategyDefinitionFactory` |
| `StrategyEvaluator` | `SharedRuntimeStrategyEvaluator` (new) | package `TradingStrategy.on_bar()` |
| `IndicatorCalculator` | `SharedRuntimeIndicatorCalculator` (new) | `finbar_strategy_runtime.indicators.PandasTaIndicatorCalculator` |

### `YamlStrategyDefinitionLoader` (kept, minimal change)
```
Input:  file path or YAML/JSON text
Output: package StrategyDefinition (finbot.domain.interfaces.StrategyDefinitionLoader
         return type is re-pointed to the package entity)
Uses:   finbar_strategy_runtime.parser.strategy_definition_parser.StrategyDefinitionParser
Bonus:  must retain the package StrategyValidationResult so callers can read
        result.required_columns (see last_validation_result() / last_required_columns())
```
Kept because file I/O + `StrategyLoadError` are Finbot conveniences. The only
change is the parser import line.

### `SharedRuntimeStrategyEvaluatorFactory` (new)
```
Input:  package StrategyDefinition, symbol, interval, strategy_hash
Output: SharedRuntimeStrategyEvaluator
Uses:   finbar_strategy_runtime.evaluation.strategy_definition_factory.StrategyDefinitionFactory
        .create(definition) -> package TradingStrategy
```
One line of real work: `strategy = StrategyDefinitionFactory().create(definition)`,
then wrap it. One package `TradingStrategy` per call (see statefulness below).

### `SharedRuntimeStrategyEvaluator` (new — the critical adapter)
```
Input:  enriched_bar (dict[str, Any]), position (PositionSnapshot)
Output: SignalDecision (Finbot domain entity)

Internal flow:
  1. Derive candle_timestamp from the bar (see note below).

  2. Build the package position dict. The package strategy uses
     position["size"] to decide entry-branch (size==0) vs exit-branch
     (size!=0), and position["direction"] to pick the exit side. This is
     REQUIRED, not optional.

       package_position = {
           "size": float(position.size),
           "direction": _direction(position.direction),
                 # LONG  -> "long", SHORT -> "short", FLAT -> ""
       }
     (entry_price is NOT used by on_bar and may be omitted.)

  3. result = self._strategy.on_bar(enriched_bar, package_position)  # SignalResult

  4. Map result -> SignalAction (see mapping table).

  5. Build SignalDecision with Finbot idempotency fields:
       symbol, interval, candle_timestamp, strategy_hash  (from ctor)
       confidence, stop_price, target_price               (from result)
```

**`SignalResult` -> `SignalAction` mapping (authoritative):**

The package `SignalResult` uses `action ∈ {buy, sell, hold}` and
`direction ∈ {long, short, exit}`. On exit the side is NOT in the result, so
the adapter must resolve it from the **current position direction**.

| result.action | result.direction | position.direction | -> SignalAction |
|---------------|------------------|--------------------|----------------|
| `hold`        | (any)            | (any)              | `HOLD` |
| `buy`         | `long`           | (any)              | `LONG_ENTRY` |
| `sell`        | `short`          | (any)              | `SHORT_ENTRY` |
| `sell`        | `exit`           | `long`             | `LONG_EXIT` |
| `buy`         | `exit`           | `short`            | `SHORT_EXIT` |
| any other     | —                | —                  | raise `ValueError` |

> This resolves a contradiction in the previous spec (which said both "pass
> position to the package" and "the adapter ignores position"). Passing the
> position to the package is mandatory; using the current position direction to
> resolve the exit side is mandatory.

**candle_timestamp derivation:** the package `TradingStrategy` does not consume
a timestamp; it comes from the Finbot bar dict. Use the same logic as the
existing `RuleBasedStrategyEvaluator`: read `bar["candle_timestamp"]` if
present, otherwise fall back to a monotonic counter. Keep this behaviour so
`signal_key` stays stable across a session.

### `SharedRuntimeIndicatorCalculator` (new, thin)
```
Input:  DataFrame of OHLCV bars, list[str] of indicator names
Output: enriched DataFrame
Uses:   finbar_strategy_runtime.indicators.pandas_ta_indicator_calculator.PandasTaIndicatorCalculator
```
A one-line delegation. It exists so Finbot depends on its own
`IndicatorCalculator` interface; the package import lives in infrastructure
only.

---

## Architecture boundary rules (enforced by tests)

| Import target | `core/domain` | `core/application` | `infrastructure` | `startup` | `presentation` |
|---------------|:-------------:|:------------------:|:----------------:|:---------:|:--------------:|
| `finbar_strategy_runtime.domain.entities.*` | ✅ allowed | ✅ allowed | ✅ allowed | ✅ allowed | ✅ allowed |
| `finbar_strategy_runtime.domain.interfaces.*` | ✅ allowed | ✅ allowed | ✅ allowed | ✅ allowed | ✅ allowed |
| `finbar_strategy_runtime.parser.*` | ❌ banned | ❌ banned | ✅ allowed | ✅ allowed | ❌ banned (use a service) |
| `finbar_strategy_runtime.evaluation.*` | ❌ banned | ❌ banned | ✅ allowed | ✅ allowed | ❌ banned |
| `finbar_strategy_runtime.indicators.*` | ❌ banned | ❌ banned | ✅ allowed | ✅ allowed | ❌ banned |
| monolithic `finbar` (the app) | ❌ banned everywhere | ❌ | ❌ | ❌ | ❌ |

**Rationale:** the package `domain/` is pure; `parser/` (PyYAML), `evaluation/`
(stateful engine), and `indicators/` (pandas/numpy) are infrastructure-tier and
must stay out of Finbot's domain/application/presentation layers. The concrete
adapters live in `infrastructure/` and are wired in `startup/`.

## Entity vs ORM separation
- Package strategy entities are pure dataclasses — no ORM.
- Finbot SQLite rows stay in
  `finbot/infrastructure/repositories/sqlite_bot_state_repository.py`.
- Strategy snapshots are serialized via the package's
  `StrategyDefinitionSerializer` (canonical dict) and stored as JSON; mappers
  live in the repository.

## Invariants
- `FinbarStrategyEvaluator` (placeholder) and the copied `RuleBasedStrategyEvaluator`
  / factory are **deleted**, not left unused.
- All copied parser/evaluator/indicator/strategy files and copied strategy
  domain entities are **deleted**.
- Production code imports `finbar_strategy_runtime` only via the allowlist above.
- Monolithic `import finbar` is banned everywhere (architecture test).
- Live/testnet/dry-run safety behaviour remains Finbot-owned.
- Strategy schema version compatibility is explicit — never guessed from the
  package version.
- Parity is **structural** (same package on both sides); the old parity test
  that imported the monolithic Finbar app is deleted.

## Statefulness contract (critical for live correctness)

- The package `TradingStrategy` (`JsonRuleBasedStrategy`) is **stateful** — it
  holds crossover tracking state. The package `IndicatorCalculator` is
  **stateless** (recomputes all columns from the full frame each call).
- Create **one** `TradingStrategy` instance per symbol per live session, inside
  `SharedRuntimeStrategyEvaluatorFactory.create(...)`, and hold it for the
  session lifetime inside the evaluator adapter.
- **Never** recreate the strategy mid-session (crossover state would reset and
  re-fire false signals).
- **Never** share one strategy instance across symbols (state corruption).
- Call `strategy.on_reset()` only when restarting a session after a full stop.
- Call `IndicatorCalculator.calculate(warmup_frame, indicators)` with the
  **full** warmup frame each bar — do not pass only the latest bar. (Finbot's
  `LiveTradingRuntimeUseCase._enrich_bars` already maintains a cached frame and
  appends one row per candle; that cached frame is what gets passed.)
