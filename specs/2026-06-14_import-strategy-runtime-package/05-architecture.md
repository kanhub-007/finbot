# Architecture Decisions — Import Shared Strategy Runtime Package

---

# ADR-1: Depend on the shared runtime package, not the Finbar application

**Context:**
Finbot must evaluate Finbar-authored strategies but must not require the Finbar
service, local checkout, REST API, MCP server, repositories, or startup code at
runtime. The strategy runtime is now a standalone, pure-ish package
(`finbar-strategy-runtime`) that both Finbar and Finbot can consume.

**Decision:**
Finbot depends on `finbar-strategy-runtime` (import `finbar_strategy_runtime`).
Production code must not import the monolithic `finbar` application.

**Consequences:**
- Finbot remains standalone (no Finbar service/checkout required).
- Strategy semantics are shared, not copied.
- Package availability/version compatibility becomes a startup dependency to
  validate (see ADR-3).

---

# ADR-2: Finbot keeps all live-trading adapters and safety logic

**Context:**
The package is suitable for both Finbar and Finbot only because it stops at
signal generation. Finbot live execution has safety, persistence, and exchange
responsibilities that Finbar backtesting does not share.

**Decision:**
The package provides parsing, validation, indicator calculation, and signal
generation. Finbot owns Hyperliquid adapters, market/account streams, risk
gates, order planning, dry-run/testnet/live branching, `cloid`, duplicate
prevention, persistence, reconciliation, account event handling, warmup, and
enrichment validation.

**Consequences:**
- Dry-run/testnet/live safety semantics remain under Finbot tests and specs.
- Package updates can never accidentally submit an order.
- Exactly one thin adapter (`SharedRuntimeStrategyEvaluator`) bridges the
  package `SignalResult` to the Finbot `SignalDecision`.

---

# ADR-3: Schema version compatibility is explicit and decoupled from package semver

**Context:**
A package release can support multiple strategy schema versions. A strategy
schema may remain stable across many package versions.

**Decision:**
Finbot compatibility checks use the package-reported supported schema versions
and capability catalog. Package semver (`__version__`) is used for
audit/diagnostics only — never to decide schema compatibility.

**Consequences:**
- Finbot can reject unsupported strategies before websocket subscription.
- Operators see clear blockers when package or strategy schema is incompatible.
- Live mode applies Finbot policy on top of package schema validation (e.g.
  "no stop loss in live mode = reject").

---

# ADR-4: Remove duplicate active implementations (single source of truth)

**Context:**
Keeping both copied Finbar runtime code and package-backed runtime code would
recreate drift inside Finbot. As of today the copies are byte-identical to the
package, but the package has since added a handler-registry indicator engine, a
unified metric catalog, dynamic-period dispatch, and a two-pass crossover-safe
evaluator — so divergence is already underway.

**Decision:**
After the package-backed adapters pass, ALL copied strategy runtime modules and
ALL copied strategy domain entities are deleted. There is exactly one active
strategy semantic implementation: the package.

**Consequences:**
- Fewer parity tests needed inside Finbot (parity is structural).
- Drift risk moves entirely to the package's own contract tests.
- Migration touches many files/imports but simplifies long-term maintenance.

---

# ADR-5: Adopt the package's strategy domain entities as Finbot's canonical domain model
**(Changed from the previous version of this spec.)**

**Context:**
The previous spec proposed keeping Finbot's *own* strategy domain entities
(`StrategyDefinition`, `Condition`, `Operand`, `SideRules`, `RiskSpec`, etc. in
`finbot/core/domain/entities/`) and writing adapter mappers between them and the
package's entities. This was self-defeating: it preserves the exact duplication
and drift surface the package was created to eliminate, and it requires a large,
brittle, forever-maintained mapper that tracks every field of every entity. The
spec also contradicted itself — its `StrategyDefinitionLoader` interface returns
a Finbot `StrategyDefinition`, but the loader adapter delegates to the package
parser which returns the *package* `StrategyDefinition`, with no clean
reconciliation.

The package's `domain/entities/` are verified pure: no numpy, pandas, framework,
filesystem, network, or database imports — only `dataclasses`/`typing`. Its
`domain/interfaces/` are plain ABCs. A pure external domain library is a
legitimate domain-layer dependency, exactly like `decimal` or `dataclasses`.

**Decision:**
Finbot deletes its copied strategy domain entities and uses the package's
directly:
- `core/domain` and `core/application` may import
  `finbar_strategy_runtime.domain.entities.*` and
  `finbar_strategy_runtime.domain.interfaces.*` (the pure subpackages).
- `core/domain`, `core/application`, and `presentation` may **not** import the
  package's `parser`, `evaluation`, or `indicators` subpackages — those are
  infrastructure-tier (PyYAML / pandas / stateful engine) and live behind the
  concrete adapters in `infrastructure/`, wired in `startup/`.
- Finbot's own live-trading entities (`SignalDecision`, `SignalAction`,
  `PositionSnapshot`, `OrderIntent`, risk/enrichment results) are NOT in the
  package and stay Finbot-owned.

**Consequences:**
- Zero entity duplication; zero entity drift (the stated goal).
- A change to a package entity shape breaks Finbot at import time — a loud,
  immediate signal rather than silent drift. This is desirable.
- The architecture test (`test_dependency_rules.py`) gains a subpackage
  allowlist that distinguishes pure package `domain.*` (allowed in Finbot
  domain) from package `parser`/`evaluation`/`indicators` (infrastructure-only).
- If, later, a hard separation is required (e.g. Finbot domain must not import
  any external package at all), the fallback is to re-introduce Finbot entities
  that subclass/re-export the package entities — but that is deferred until
  there is a concrete reason, because it re-introduces a drift surface.
