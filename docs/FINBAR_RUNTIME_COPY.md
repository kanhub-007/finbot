# Finbar Runtime Copy — Superseded

> **Status: SUPERSEDED.** The copied Finbar strategy runtime has been removed.
> Finbot now depends on the published **`finbar-strategy-runtime`** package
> (imported as `finbar_strategy_runtime`).

The previous contents of this document (an inventory of copied files) are no
longer relevant. The copy has been deleted in favour of the shared package so
that **a live trade and a backtest run the exact same strategy code** — there
is no possibility of semantic drift between the two.

## Where the strategy runtime now lives

| Concern | Location |
|---------|----------|
| Strategy domain entities (pure) | `finbar_strategy_runtime.domain.entities.*` |
| Strategy interfaces (pure ABCs) | `finbar_strategy_runtime.domain.interfaces.*` |
| Parser / validation | `finbar_strategy_runtime.parser.*` |
| Evaluation engine | `finbar_strategy_runtime.evaluation.*` |
| Indicator engine (pandas/numpy) | `finbar_strategy_runtime.indicators.*` |

## Finbot-owned adapters (the bridge)

Finbot keeps four thin adapters in `finbot/infrastructure/` that bridge
Finbot-shaped interfaces to the package:

| Finbot interface | Adapter | Delegates to (package) |
|------------------|---------|------------------------|
| `StrategyDefinitionLoader` | `YamlStrategyDefinitionLoader` | `parser.StrategyDefinitionParser` |
| `StrategyEvaluatorFactory` | `SharedRuntimeStrategyEvaluatorFactory` | `evaluation.StrategyDefinitionFactory` |
| `StrategyEvaluator` | `SharedRuntimeStrategyEvaluator` | package `TradingStrategy.on_bar()` |
| `IndicatorCalculator` | `SharedRuntimeIndicatorCalculator` | `indicators.PandasTaIndicatorCalculator` |

The package stops at **signal generation** (`SignalResult`). Everything after
that — order planning, risk gates, dry-run/testnet/live branching, `cloid`
idempotency, persistence, reconciliation — stays Finbot-owned.

## Architecture rules

- Production code imports `finbar_strategy_runtime` only via the allowlist in
  `specs/2026-06-14_import-strategy-runtime-package/03-domain.md`.
- The pure `domain.*` subpackages may be imported anywhere; `parser`,
  `evaluation`, and `indicators` are infrastructure-only (enforced by
  `tests/test_architecture/test_dependency_rules.py`).
- The monolithic `finbar` application is banned everywhere.

See the spec `specs/2026-06-14_import-strategy-runtime-package/` for the full
rationale and architecture decisions (ADR-1 through ADR-5).
