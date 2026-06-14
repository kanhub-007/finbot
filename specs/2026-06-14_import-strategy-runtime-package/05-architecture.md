# ADR-1: Depend on shared runtime package, not the Finbar application

**Context:**
Finbot must evaluate Finbar-authored strategies but must not require the Finbar service, local checkout, REST API, MCP server, repositories, or startup code at runtime.

**Decision:**
Finbot depends on `finbar-strategy-runtime` / `finbar_strategy_runtime`. Production code must not import `finbar`.

**Consequences:**
- Finbot remains standalone.
- Strategy semantics are shared without copying code.
- Package availability/version compatibility becomes a startup dependency to validate.

---

# ADR-2: Finbot keeps all live-trading adapters and safety logic

**Context:**
The shared package is suitable for Finbar and Finbot only if it stops before application-specific intent. Finbot live execution has safety, persistence, and exchange responsibilities that Finbar backtesting does not share.

**Decision:**
The package provides parsing, validation, enrichment, and signal generation. Finbot owns Hyperliquid adapters, market streams, risk gates, order planning, dry-run/testnet/live branching, `cloid`, duplicate prevention, persistence, reconciliation, account event handling, and CLI/MCP control.

**Consequences:**
- Dry-run/testnet/live safety semantics remain under Finbot tests and specs.
- Package updates cannot accidentally submit orders.
- Adapters/mappers are required at the package-to-Finbot boundary.

---

# ADR-3: Schema version compatibility is explicit

**Context:**
A package release can support multiple strategy schema versions. A strategy schema may remain stable across many package versions.

**Decision:**
Finbot compatibility checks use package-reported supported schema versions and capabilities. Package semver is used for audit/diagnostics only.

**Consequences:**
- Finbot can reject unsupported strategies before websocket subscription.
- Operators see clear blockers when package or strategy schema is incompatible.
- Live mode can apply stricter policies on top of package schema validation.

---

# ADR-4: Remove duplicate active implementations

**Context:**
Keeping both copied Finbar runtime code and package-backed runtime code would recreate drift inside Finbot.

**Decision:**
After package-backed adapters are passing, copied runtime modules should be removed or converted into temporary compatibility shims with deprecation dates. There must be one active strategy semantic implementation.

**Consequences:**
- Fewer parity tests are needed inside Finbot.
- Drift risk moves to package contract tests.
- Migration may touch many imports but simplifies long-term maintenance.
