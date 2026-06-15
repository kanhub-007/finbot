# Import Shared Strategy Runtime Package

## User Story
As a Finbot maintainer, I want Finbot to use the published `finbar-strategy-runtime`
package instead of its copied Finbar code, so that **a live trade and a backtest
run the exact same strategy code** and there is no possibility of semantic drift
between the two.

## Prerequisites
- `finbar-strategy-runtime` is extracted and available. **Status (verified
  2026-06-15): DONE.** The package exists at
  `C:/HAL/Github/finbar/packages/strategy-runtime/`, is importable as
  `finbar_strategy_runtime` (`__version__ == "0.1.0"`), and is already installed
  editable into Finbot's venv. No PyPI publish is required to start.
- The crossover-state refactor (`finbar` spec
  `2026-06-14_separate-crossover-state-from-evaluation`) is **DONE** — the
  package's `JsonRuleBasedStrategy` now records crossover state in a separate
  pass, so short-circuiting booleans never loses state. This spec depends on
  that behaviour.

## Context

Finbot currently contains **adapted copies** of Finbar's strategy runtime inside
`finbot/infrastructure/strategy/` (parser, condition evaluator, indicator
catalog/calculator, risk calculator, rule-based strategy) and **copied domain
entities** inside `finbot/core/domain/entities/` (`StrategyDefinition`,
`Condition`, `ConditionGroup`, `Operand`, `SideRules`, `RiskSpec`,
`IndicatorSpec`, `FeatureSpec`, etc.). The copy was made so Finbot did not need
a runtime dependency on the Finbar *application*.

The cost is drift. As of today the copied entities are byte-identical to the
package's (only the import path differs), but the package has since grown a
handler-registry indicator engine, a unified metric catalog, dynamic-period
dispatch, and a two-pass crossover-safe evaluator — none of which the Finbot
copy has. A live trade evaluated by Finbot's copy can already diverge from a
backtest evaluated by the package. **This is exactly the bug class this
migration exists to remove.**

The fix is structural: delete the copies and depend on the package. The package
stops at **signal generation** (`SignalResult`). Everything after that — order
planning, risk gates, dry-run/testnet/live branching, `cloid` idempotency,
persistence, reconciliation, account websocket handling, CLI/MCP control — stays
Finbot-owned.

### One important design change from the previous version of this spec

The previous spec proposed keeping Finbot's *own* strategy domain entities and
writing adapter mappers between them and the package's entities. **That is
self-defeating**: it preserves the duplication and the drift surface the package
was created to eliminate, and it requires a large brittle mapper that must track
every field of every entity forever.

Instead, this spec adopts the package's strategy domain model as Finbot's
canonical strategy domain model. Rationale and the architecture-test rule that
keeps this safe are in `05-architecture.md` (ADR-5) and `03-domain.md`.

## Non-Goals
- Importing the monolithic `finbar` application (`import finbar`). Still banned.
- Calling Finbar REST/MCP services at runtime.
- Moving Finbot live-trading adapters, repositories, risk gates, order
  planning, reconciliation, or exchange code into the shared package.
- Changing live-mode safety requirements (dry-run default, explicit live ack,
  reduce-only exits, etc.).
- Letting the package import Finbot (dependency direction is one-way).
- Silently enabling unsupported strategy schema versions.
