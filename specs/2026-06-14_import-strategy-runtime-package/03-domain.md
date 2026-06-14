# Domain Model — Import Shared Strategy Runtime Package

## Entities
| Entity | Fields | Behaviour | Persisted? |
|--------|--------|-----------|------------|
| Package `StrategyDefinition` | schema, params, indicators, features, risk, sides | Defines executable strategy | Snapshot persisted by Finbot |
| Package `SignalResult` | action/side/confidence/stop/target/context | Package strategy output | Mapped to Finbot signal records |
| Finbot `SignalDecision` | action, symbol, interval, candle timestamp, strategy hash, prices | Bot-safe signal for order planning | Yes |
| Finbot `OrderIntent` | side, size, reduce_only, cloid, signal key | Planned order | Yes |
| Finbot `RiskDecision` | decision, reason, context | Risk gate outcome | Yes |
| Finbot `EnrichmentValidationResult` | missing/non-finite/invalid columns | Blocks unsafe evaluation | Yes via audit/risk event |
| `RuntimeCapabilitySnapshot` | package name/version, supported schema versions, indicators, operators | Startup compatibility evidence | Yes via audit/config snapshot |

## Value Objects
| Name | Fields | Used where |
|------|--------|------------|
| `StrategySchemaVersion` | e.g. `2.0` | Compatibility; separate from package semver |
| `RuntimePackageVersion` | e.g. `0.1.0` | Diagnostics and audit only |
| `SignalKey` | strategy_hash, symbol, interval, candle timestamp, action | Duplicate prevention |
| `SharedRuntimeSignalMapping` | package action -> Finbot action | Adapter boundary |

## Interfaces (for DI)
| Interface | Methods | Implemented by |
|-----------|---------|----------------|
| `StrategyDefinitionLoader` | `load_from_file`, `load_from_text` | Package-backed loader adapter |
| `StrategyEvaluatorFactory` | `create(definition, symbol, interval, strategy_hash)` | Package-backed evaluator factory adapter |
| `StrategyEvaluator` | `evaluate(enriched_bar, position) -> SignalDecision` | Adapter wrapping package runtime strategy |
| `IndicatorCalculator` | `calculate(frame, indicators)` | Package-backed calculator adapter |
| `StrategyCompatibilityChecker` | `check(definition, mode) -> StrategyCompatibilityResult` | Finbot service using package capabilities plus Finbot live policies |

## Adapter boundary
- Package entities may be used directly for strategy definitions if doing so does not leak live-trading concerns into the package.
- Package signal outputs must be mapped to Finbot `SignalDecision` before risk gates and order planning.
- Finbot owns all order, exchange, persistence, reconciliation, risk-gate, and live-mode entities.
- The shared package must not import `finbot`.

## Entity vs ORM separation
- Package entities are pure and not ORM models.
- Finbot SQLite rows remain in `finbot/infrastructure/repositories/sqlite_bot_state_repository.py` and migration SQL.
- Any package-to-row mapping happens in Finbot infrastructure repositories or startup adapters, never in the package.

## Invariants
- Finbot production code must not import the monolithic `finbar` app.
- Finbot may import `finbar_strategy_runtime` in infrastructure/startup and, if approved, application services via domain interfaces. Domain entities should avoid importing external package types unless the package becomes the canonical domain model.
- Live/testnet/dry-run safety behaviour remains Finbot-owned.
- Strategy schema version compatibility is explicit and never guessed from package version.
