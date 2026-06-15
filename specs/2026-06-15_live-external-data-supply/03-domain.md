# Domain Model — Live External Data Supply

## Live support tiers (the central model)

Finbot declares which `DataClass` values (package enum) it can supply on the
**live** side. This table is the single source of truth for capability gating.

| `DataClass` | Live support | How supplied | Slice |
|-------------|:------------:|--------------|:-----:|
| `DAILY_OHLCV` | ✅ | Hyperliquid candles (existing) | migration |
| `INTRADAY_OHLCV` | ✅ | Hyperliquid candles (existing) | migration |
| `DERIVATIVES` | ✅ | Hyperliquid funding/OI (Slice 2); CoinGlass L-S/CVD/liquidations (Slice 3) | 2–3 |
| `INTRADAY_OHLCV` finer than bar (realized vol family) | ⚠️ proxy only | Via `MetricResolutionPath` proxy on bar OHLCV | 4 |
| `TRADES`, `QUOTES`, `TRADES_AND_QUOTES` | ❌ | Not built — reject upfront | 4 |
| `LEVEL_2_ORDER_BOOK`, `ORDER_BOOK_EVENTS` | ❌ | Not built — reject upfront | 4 |
| `EXTERNAL_PROVIDER` | ❌ (unless mapped to a Finbot source) | Per-provider decision | 4 |

> The capability resolver (below) consumes this table. Adding a data source to
> Finbot = flipping one row from ❌ to ✅ and wiring the source. No other code
> changes are needed for gating to accept the newly supplyable strategies.

## Package entities Finbot adopts (used directly)

| Entity | Source | Used by Finbot for |
|--------|--------|--------------------|
| `DataClass` | `finbar_strategy_runtime.domain.entities.data_class` | Classifying what a metric needs |
| `DataRequirement` | `...domain.entities.data_requirement` | Per-metric input requirements |
| `MarketMetricDefinition` | `...domain.entities.market_metric_definition` | What each metric needs + its resolution paths |
| `MetricResolutionPath` | `...domain.entities.metric_resolution_path` | Ordered, confidence-ranked alt computation paths |
| `MetricCapabilityResult` | `...domain.entities.metric_capability_result` | Output of a capability check |
| `MetricFamily`, `MetricConfidence` | `...domain.entities.*` | Categorisation / confidence labels |

## Package services/interfaces Finbot uses

| Interface | Source | Finbot use |
|-----------|--------|------------|
| `MarketMetricCatalog` | `...domain.interfaces.market_metric_catalog` | Query metric requirements + best resolution path |
| `UnifiedMetricCatalog` | `...parser.unified_metric_catalog` (concrete) | Default implementation, wired in startup |
| `merge_derivatives_asof` | `...indicators.derivatives_merge` (extracted in Slice 2) | No-lookahead as-of join of derivatives onto OHLCV |
| `interval_offset` | `...indicators.bar_merger` | The offset authority both backtest and live use |

## Finbot-owned entities (new)

| Entity | Fields | Behaviour | Persisted? |
|--------|--------|-----------|------------|
| `DerivativesMetrics` | symbol, timestamp, the 11 `DERIVATIVES_FIELDS`, interval, metadata | Provider-agnostic derivatives point | Cached in SQLite (optional) |
| `ExternalDataSourceType` | enum: `hyperliquid_derivatives`, `coinglass_derivatives` | Identifies a source | Yes (config/audit) |
| `LiveDataCapability` | available_data_classes: set[DataClass], sources: dict | Finbot's declared live supply | Yes (audit) |
| `LiveCapabilityReport` | supported: bool, supplied: list, missing: list, proxies_used: list, reason | Output of capability resolution | Transient -> audit |

> **`DerivativesMetrics` reuse:** this entity currently lives in the Finbar app.
> Slice 2 extracts it (and `merge_derivatives_asof`) into the package so Finbot
> imports the same class. The field list `DERIVATIVES_FIELDS` already lives in
> the package (`indicators/derivatives_constants.py`) — the entity is moved to
> match.

## Finbot-owned interfaces (new)

| Interface | Methods | Implemented by |
|-----------|---------|----------------|
| `ExternalDerivativesSource` | `fetch_recent(symbol, interval, count) -> list[DerivativesMetrics]` | `HyperliquidDerivativesSource`, `CoinGlassDerivativesSource` |
| `LiveCapabilityResolver` | `resolve(definition) -> LiveCapabilityReport` | Finbot service using `MarketMetricCatalog` + the tier table |
| `ExternalDataMerger` | `merge(ohlcv_frame, interval) -> frame` | `DerivativesFrameMerger` (delegates to package `merge_derivatives_asof`) |

## Finbot-owned entities (unchanged, reused)

`SignalDecision`, `SignalAction`, `EnrichmentValidationResult`,
`CandleProcessingResult`, `WarmupWindow`, `BarFrameConverter`,
`PandasBarFrameConverter` — all unchanged from the migration spec.

## Injection point (critical — where external columns enter the live frame)

```
LiveTradingRuntimeUseCase.process_closed_candle(candle):
    1. warmup.append(candle)            # unchanged
    2. enriched = self._enrich_bars()
         2a. build/append OHLCV frame                 # unchanged
         2b. NEW: enriched = self._external_data_merger.merge(enriched, interval)
         2c. enriched = indicator_calculator.calculate(enriched, required_columns)
    3. validation = enrichment_validator.validate(...)   # unchanged; now sees external cols
    4. signal = evaluator.evaluate(latest, position)     # unchanged
    ...
```

Step 2b is the **only** pipeline change. It is the live analogue of Finbar's
`_merge_derivatives_if_needed`. When `ExternalDataMerger` is a no-op (no
sources wired), the pipeline is identical to the post-migration OHLCV path.

## Capability resolution algorithm (LiveCapabilityResolver)

```
for each concrete metric in definition.required_indicators:
    defn = catalog.get(metric_name)            # MarketMetricDefinition
    if defn is None:
        reject("unknown metric: {name}")
    if any(defn.required_data_classes) in finbot.available_data_classes:
        record supplied
        continue
    # try resolution paths in priority order
    for path in defn.resolution_paths:
        if path.required_data_class in finbot.available_data_classes:
            record proxy_used(path); break
    else:
        record missing(defn.required_data_classes)
if any missing and no acceptable proxy:
    return LiveCapabilityReport(supported=False, missing=..., reason=...)
return LiveCapabilityReport(supported=True, ...)
```

This is pure domain logic over package-provided metadata — no I/O.

## Invariants

- The **no-lookahead** offset for derivatives is computed by the package's
  `interval_offset`, never reimplemented in Finbot.
- A derivatives value published at T is visible only at bar T+interval in both
  backtest and live. Parity is structural (same merge function).
- Missing external data produces `NaN` columns, never an exception during
  enrichment. The `EnrichmentValidator` + capability resolver decide whether
  that NaN blocks the strategy.
- External data sources are **optional and pluggable**. A pure-OHLCV Finbot
  deployment with zero sources configured still runs OHLCV strategies with full
  parity.
- Capability gating runs **before** websocket subscription: an unsupplied
  strategy never starts consuming market data.

## Entity vs ORM separation
- `DerivativesMetrics` is a pure dataclass (no ORM) in the package.
- Finbot's optional derivatives cache is a SQLite table in
  `infrastructure/repositories/`, with a mapper to/from the package entity.
- No ORM types leak into domain/application layers.

## Statefulness contract
- `ExternalDerivativesSource` implementations are **stateless** fetchers; they
  may cache HTTP responses internally but expose no per-session state.
- `DerivativesFrameMerger` is **stateless** — it re-merges from the source rows
  each call (the source holds the history).
- The live warmup frame is the only stateful object, already managed by
  `LiveTradingRuntimeUseCase`.
