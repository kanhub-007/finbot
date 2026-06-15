# Architecture Decisions — Live External Data Supply

---

# ADR-1: External data supply is a separate axis from evaluation logic

**Context:**
After the runtime-package migration, backtest and live share the same
evaluation code for OHLCV strategies. But some strategies reference non-OHLCV
columns (funding rate, open interest, liquidations, L/S ratio, CVD). In Finbar's
backtest these are pre-merged onto the frame *before* `calculate()`; the
package's indicator handlers are pass-throughs that only ensure the column
exists. Finbot's live pipeline previously fed OHLCV only.

**Decision:**
Treat external data as a **supply concern**, orthogonal to evaluation. Finbot
supplies the same columns Finbar supplies, using the same no-lookahead merge,
and queries the package's metric catalog to know — deterministically — which
strategies it can and cannot supply.

**Consequences:**
- Evaluation logic stays 100% shared via the package (no fork for external data).
- "Can Finbot live-trade strategy X?" becomes a data-availability question with
  a machine-checkable answer, not a guess.
- Adding a new data source is additive: wire a source + flip a support-tier row.

---

# ADR-2: Extract the derivatives merge into the package (second small extraction)

**Context:**
`DerivativesMetrics` and `merge_derivatives_asof` currently live in the Finbar
app. The package's derivatives pass-through handlers depend on those columns
being present, and the no-lookahead offset (`interval_offset`) already lives in
the package. If Finbot reimplements the merge, the same `(ohlcv, derivatives)`
inputs can diverge between backtest and live — recreating the exact drift class
the runtime package was created to eliminate.

**Decision:**
Move `DerivativesMetrics` and `merge_derivatives_asof` into the package
(`finbar_strategy_runtime.domain.entities.derivatives_metrics` and
`finbar_strategy_runtime.indicators.derivatives_merge`). Both Finbar and Finbot
import them from there. Finbar's app copies are deleted.

**Consequences:**
- One merge implementation; structural parity for derivatives strategies.
- The package grows a small "data merge" surface, consistent with it already
  owning `merge_timeframes` / `interval_offset`.
- A future third consumer (e.g. an optimiser) reuses the same merge for free.

---

# ADR-3: Capability gating runs before websocket subscription

**Context:**
A strategy that Finbot cannot supply data for must not start consuming market
data — that wastes resources and, worse, could place the runtime in a state
where it silently HODLs because required columns are NaN.

**Decision:**
`LiveCapabilityResolver.resolve(definition)` runs in `service_factory` /
`start_live` **before** the bot loop and market-data stream are constructed. On
`supported=False`, the run is rejected with a named reason and no subscription
occurs.

**Consequences:**
- Operators get fast, clear feedback for unsupplied strategies.
- The live runtime is never asked to evaluate a strategy it can't feed.
- Capability resolution is pure (no I/O), so it is trivially testable.

---

# ADR-4: External data sources are optional and pluggable

**Context:**
Not every Finbot deployment will want (or be able) to fetch CoinGlass data, and
pure-OHLCV strategies must never pay the cost or take the dependency of
external fetching.

**Decision:**
External data sources are injected (`ExternalDerivativesSource` interface) and
default to absent. `LiveDataCapability.available_data_classes` is derived from
which sources are wired. With zero sources, Finbot runs OHLCV strategies with
full parity and performs zero external network calls.

**Consequences:**
- Minimal deployments stay minimal.
- Capability gating automatically narrows to OHLCV when no sources are wired.
- New data classes are unlocked by wiring a source + extending the tier table.

---

# ADR-5: Unsupported data classes are rejected, not silently approximated

**Context:**
Some `DataClass` values (`LEVEL_2_ORDER_BOOK`, `TRADES`, `ORDER_BOOK_EVENTS`)
require infrastructure Finbot does not have and will not build in this spec.
Silently substituting a poor proxy would break the "what I backtested is what I
trade" guarantee.

**Decision:**
The resolver rejects strategies requiring an unsupplied data class unless that
metric has an explicit, confidence-ranked `MetricResolutionPath` whose required
data class Finbot *can* supply. Rejection messages name the data class and, when
relevant, suggest the available proxy.

**Consequences:**
- No silent divergence: either we run the real (or an explicitly-labelled proxy)
  path, or we refuse.
- The `MetricResolutionPath` machinery already in the package makes "proxy with
  a confidence label" first-class rather than ad-hoc.
- Future support for L2/trades is unlocked by flipping a tier row + building a
  source; the gating code does not change.

---

# ADR-6: Live supply is declared per DataClass, not per metric

**Context:**
A metric-level allowlist (like Finbot's current `_KNOWN_INDICATORS`) drifts
whenever the package adds a metric, and it doesn't express *why* a metric is
unavailable (missing data vs. unimplemented logic).

**Decision:**
Finbot declares the `DataClass` values it can supply. Capability resolution
joins that against each metric's `required_data_classes` from the package
catalog. Metric-level support is *derived*, not hand-maintained.

**Consequences:**
- When the package adds a metric whose data class Finbot already supplies,
  Finbot accepts it automatically — no Finbot code change.
- The reason a metric is unavailable is always "missing data class X", which is
  actionable and accurate.
