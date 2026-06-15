# Live External Data Supply (Parity for Non-OHLCV Strategies)

## User Story
As a Finbot maintainer, I want Finbot to be able to live-trade *any* strategy a
user can author in Finbar — including strategies that use funding rate, open
interest, liquidations, and L/S ratio — so that "what I backtested is what I
trade" holds for the full strategy vocabulary, not just OHLCV-only strategies.

## Prerequisites
- **`2026-06-14_import-strategy-runtime-package` must be completed first.**
  That migration makes Finbot reuse the package's parser/evaluator/indicator
  engine for OHLCV strategies. This spec extends the same live pipeline to
  supply the *external data* those engines consume.
- The package must keep `interval_offset` / `merge_timeframes`
  (`finbar_strategy_runtime.indicators.bar_merger`) — it does today.

## Context

After the import-runtime migration, any strategy whose indicators derive purely
from OHLCV produces byte-identical signals in a Finbar backtest and a Finbot
live trade, because both call the same package code on the same OHLCV frame.
**That is the reuse the user is asking about, and it works.**

This spec covers the strategies the migration does *not* yet unlock: those that
reference **external (non-OHLCV) columns**. The mechanism is well-understood and
verified:

- Finbar's backtest pre-merges external columns onto the OHLCV frame *before*
  `indicator_calculator.calculate()`. The canonical example is derivatives:
  `CachedPriceIndicatorJobRunner._merge_derivatives_if_needed()` calls
  `merge_derivatives_asof(frame, derivatives_rows, interval)` so that by the
  time the package's indicator handlers run, columns like `funding_rate`,
  `open_interest`, `liquidations_long_1h` already exist on the frame.
- The package's derivatives handlers are **pass-through**: they only guarantee
  the column exists (writing `NaN` if absent). They do not fetch anything. So
  "supply the data" is the caller's (backtest *or* live) responsibility.
- Finbot's live pipeline currently feeds **OHLCV only**. For an external-data
  strategy, the columns arrive as `NaN`, Finbot's `EnrichmentValidator` blocks
  evaluation (or the strategy silently HODLs forever). That is the entire gap.

So this is a **data-supply** spec, not a logic spec. The evaluation logic is
already shared via the package; we just need Finbot to supply the same
columns Finbar supplies, with the same no-lookahead discipline, and to know —
deterministically — which strategies it can and cannot supply data for.

### Why this needs shared merge code, not a Finbot copy

`DerivativesMetrics` (the entity) and `merge_derivatives_asof` (the no-lookahead
as-of join) currently live in the **Finbar app**, not in the package. If Finbot
reimplements them, the same strategy will diverge between backtest and live
whenever the merge logic differs (offset math, NaN handling, timezone
normalisation). That is exactly the drift class the runtime package exists to
kill. This spec therefore proposes a **second small extraction** — move
derivatives merge into the package — so both contexts call the identical merge.

### The package already tells us what each strategy needs

The package's `UnifiedMetricCatalog` / `MarketMetricCatalog` declare, per metric:
`required_data_classes` (a list of `DataClass` enum values like
`INTRADAY_OHLCV`, `DERIVATIVES`, `LEVEL_2_ORDER_BOOK`), `required_columns`,
`required_providers`, and one or more `MetricResolutionPath`s (each with a
`confidence` and its own data requirements). Finbot can query this to answer,
per strategy: "can I supply every required data class? if not, is there an
acceptable proxy path? if not, reject before subscribing." This makes
live-tradeability a **deterministic, data-driven** decision instead of a guess
or a hand-maintained indicator whitelist.

## Non-Goals
- Changing the evaluation/strategy logic (that is the runtime package's job).
- Supporting data classes that require infrastructure Finbot does not have and
  will not build soon (live L2 order book, full trade tape). These are
  **documented as unsupported and rejected upfront** by capability gating — see
  the support-tier table in `03-domain.md`.
- Re-implementing Finbar's CoinGlass/Hyperliquid data fetchers verbatim.
  Finbot fetches its own live streams; it reuses only the **merge + entity**
  contract from the package.
- Moving Finbar's SQL repositories, job managers, or fetch jobs into the package.
- Changing live-mode safety requirements.
