# Implementation Guide — Live External Data Supply

Ordered so each slice ships independently and each step compiles before the
next. Run the **Verify** command after every step. Paths are relative to the
repo root of whichever repo the step targets; the step names the repo.

> **Two repos are involved:** the package
> (`C:/HAL/Github/finbar/packages/strategy-runtime/`) and Finbot
> (`C:/HAL/Github/finbot/`). Slice 2 touches the package first (extraction),
> then Finbot.

**Prerequisite:** complete `2026-06-14_import-strategy-runtime-package` first.

---

## Slice 1 — Capability-aware gating

### Step 1: Add the capability resolver
**Repo:** Finbot. **Files (new):**
- `finbot/core/domain/entities/external_data_source_type.py` — enum
- `finbot/core/domain/entities/live_data_capability.py` — declared supply
- `finbot/core/domain/dto/live_capability_report.py` — resolution output
- `finbot/core/domain/interfaces/market_metric_catalog.py` — re-export/protocol
  (or import `MarketMetricCatalog` from the package directly)
- `finbot/core/domain/services/live_capability_resolver.py` — `LiveCapabilityResolver`

`LiveCapabilityResolver` implements the algorithm in `03-domain.md`. It depends
only on `MarketMetricCatalog` (package interface) and
`MarketMetricDefinition` / `MetricResolutionPath` / `DataClass` (package
entities) + Finbot's `LiveDataCapability`. **No I/O.**

```python
class LiveCapabilityResolver:
    def __init__(self, catalog: MarketMetricCatalog, capability: LiveDataCapability):
        self._catalog = catalog
        self._capability = capability

    def resolve(self, definition: StrategyDefinition) -> LiveCapabilityReport:
        required = _concrete_required_metrics(definition)  # from required_indicators
        supplied, missing, proxies = [], [], []
        for name in required:
            defn = self._catalog.get(name)
            if defn is None:
                return LiveCapabilityReport(False, missing=[name], reason=f"unknown metric: {name}")
            if self._can_supply(defn.required_data_classes):
                supplied.append(name); continue
            proxy = self._best_proxy(defn)
            if proxy is not None:
                proxies.append((name, proxy)); continue
            missing.extend(defn.required_data_classes)
        if missing:
            return LiveCapabilityReport(False, supplied=supplied, missing=sorted(set(missing)),
                                        proxies_used=proxies, reason="unsupplied data classes")
        return LiveCapabilityReport(True, supplied=supplied, proxies_used=proxies)

    def _can_supply(self, required: tuple[DataClass, ...]) -> bool:
        return any(cls in self._capability.available_data_classes for cls in required)

    def _best_proxy(self, defn: MarketMetricDefinition) -> str | None:
        for path in sorted(defn.resolution_paths, key=lambda p: p.priority):
            if path.required_data_class in self._capability.available_data_classes:
                return path.metric_name
        return None
```

**Verify:** `python -m pytest tests/test_domain/test_live_capability_resolver.py -q`

### Step 2: Wire the resolver into live startup
**Repo:** Finbot. **File:** `finbot/startup/service_factory.py`

In `create_live_trading_runtime_use_case(...)`:
- Build a `LiveDataCapability` from wired sources (start with
  `{DataClass.INTRADAY_OHLCV}` — derivatives added in Slice 2).
- Construct `LiveCapabilityResolver(UnifiedMetricCatalog(), capability)`.
- Call `resolver.resolve(definition)` after loading the strategy; on
  `supported=False`, return a rejected `RunBotResult` (mirror the existing
  `_check_strategy_compat` rejection path) **before** building the bot loop.

**Verify:** `python -m pytest tests/test_application/test_live_trading_runtime.py tests/test_startup/test_service_factory.py -q`

### Step 3: Tests + fixtures
**Repo:** Finbot. **Files (new):**
- `tests/fixtures/strategies/l2_book_strategy.yaml` — uses a metric requiring
  `LEVEL_2_ORDER_BOOK` (reject case)
- `tests/test_domain/test_live_capability_resolver.py` — Slice-1 Scenario tests

**Verify:** `python -m pytest tests/test_domain/test_live_capability_resolver.py -q`
**Common mistake:** doing the capability check *after* subscribing to market data. It must run before.

---

## Slice 2 — Derivatives data supply

### Step 4: Extract derivatives merge into the package
**Repo:** package. Move:
- `finbar/core/domain/entities/derivatives_metrics.py` →
  `finbar_strategy_runtime/domain/entities/derivatives_metrics.py`
- `finbar/infrastructure/services/derivatives_merger.py` →
  `finbar_strategy_runtime/indicators/derivatives_merge.py`

Rewrite imports inside the moved files to `finbar_strategy_runtime.*`. The merge
already depends only on the package's `interval_offset` + the entity, so it is
clean to extract.

Update the package's `derivatives_constants.py` to re-export `DERIVATIVES_FIELDS`
from the new entity location (or keep it where it is and have the entity import
it — pick one, document it).

**Repo:** Finbar. Update `indicator_job_runner.py` and `derivatives_merger`
callers to import from the package; delete the Finbar-side copies.

**Verify (package repo):**
```bash
cd C:/HAL/Github/finbar/packages/strategy-runtime
python -c "from finbar_strategy_runtime.indicators.derivatives_merge import merge_derivatives_asof; print('ok')"
python -m pytest tests -q
```
**Verify (Finbar repo):** `python -m pytest tests -q` (Finbar's own backtest tests still pass against the extracted merge).
**Common mistake:** leaving a Finbar-side copy "just in case". Delete it — same single-source rule as the runtime extraction.

### Step 5: Finbot external-data source + merger
**Repo:** Finbot. **Files (new):**
- `finbot/core/domain/entities/derivatives_metrics.py` — re-export from package
  (`from finbar_strategy_runtime.domain.entities.derivatives_metrics import DerivativesMetrics, DERIVATIVES_FIELDS`) for convenience aliasing
- `finbot/core/domain/interfaces/external_derivatives_source.py` —
  `ExternalDerivativesSource` ABC
- `finbot/infrastructure/adapters/hyperliquid_derivatives_source.py` —
  `HyperliquidDerivativesSource` (uses `info.funding_history` +
  `meta_and_asset_ctxs`; maps to `DerivativesMetrics`)
- `finbot/infrastructure/adapters/in_memory_derivatives_source.py` — fake for tests
- `finbot/infrastructure/strategy/derivatives_frame_merger.py` —
  `DerivativesFrameMerger` (delegates to package `merge_derivatives_asof`)
- `finbot/core/domain/interfaces/external_data_merger.py` — `ExternalDataMerger` ABC

`HyperliquidDerivativesSource.fetch_recent(...)` mirrors finbar's
`hyperliquid_fetcher.fetch_funding_history` + the perp/hip3
`meta_and_asset_ctxs` funding/OI extraction (verified methods exist). On any
network error, return `[]` (runtime degrades to NaN columns).

**Verify:**
```bash
ruff check finbot/infrastructure/adapters/hyperliquid_derivatives_source.py
python -m pytest tests/test_infrastructure/test_hyperliquid_derivatives_source.py -q
```

### Step 6: Inject the merge into the live pipeline
**Repo:** Finbot. **File:** `finbot/core/application/use_cases/live_trading_runtime.py`

1. Add a constructor param `external_data_merger: ExternalDataMerger | None = None`.
2. In `_enrich_bars()`, after the OHLCV frame is built/appended and **before**
   `self._indicator_calc.calculate(...)`, call:
   ```python
   if self._external_data_merger is not None:
       df = self._external_data_merger.merge(df, interval=self._interval)
   ```
3. Keep everything else identical.

**Repo:** Finbot. **File:** `finbot/startup/service_factory.py` — wire
`DerivativesFrameMerger(source=HyperliquidDerivativesSource(...))` when a
derivatives strategy is detected (or always; the merger is a no-op when no
derivatives columns are requested — confirm via
`required_columns ∩ DERIVATIVES_FIELDS`). Update `LiveDataCapability` to include
`DataClass.DERIVATIVES` when the source is wired.

**Verify:** `python -m pytest tests/test_application/test_live_trading_runtime.py -q`
**Common mistake:** merging *after* `calculate()`. The package derivatives handlers are pass-throughs that need the columns present *before* indicator calc.

### Step 7: Cross-context parity test
**Repo:** Finbot. **File (new):** `tests/test_integration/test_derivatives_merge_parity.py`

Feed identical `(ohlcv_frame, derivatives_rows, interval)` to the package
`merge_derivatives_asof` and to Finbot's `DerivativesFrameMerger`; assert the
output frames are equal. Then feed the merged bar to the package evaluator and
assert the `SignalDecision` matches the expected fixture outcome.

**Verify:** `python -m pytest tests/test_integration/test_derivatives_merge_parity.py -q`

---

## Slice 3 — CoinGlass-backed metrics + resilience

### Step 8: CoinGlass source (optional, key-gated)
**Repo:** Finbot. **Files (new):**
- `finbot/infrastructure/adapters/coinglass_derivatives_source.py` —
  `CoinGlassDerivativesSource(api_key: str | None)`. Implements the same
  `ExternalDerivativesSource` interface. When `api_key is None`, every fetch
  returns `[]`.
- Add `coinglass_api_key` to `finbot/config/settings.py` (SecretStr, optional).

Mirror finbar's `coinglass_client.py` fetch shapes for open_interest,
liquidations, L/S ratio, CVD. Apply rate-limit backoff on 429 (degrade to `[]`).

**Repo:** Finbot. **File:** `finbot/startup/service_factory.py` — compose both
sources into a single `ExternalDerivativesSource` (e.g. a small
`CompositeDerivativesSource` that merges rows by timestamp, last-wins).

**Verify:** `python -m pytest tests/test_infrastructure/test_coinglass_derivatives_source.py -q`

### Step 9: Optional derivatives cache
**Repo:** Finbot. **Files (new):**
- `finbot/infrastructure/repositories/sql_derivatives_cache_repository.py` +
  migration — cache fetched rows to avoid re-fetching warmup history each restart.
- Wire behind a flag; default off in Slice 3.

**Verify:** `python -m pytest tests/test_infrastructure/test_sql_derivatives_cache_repository.py -q`
**Common mistake:** caching without the no-lookahead offset baked into the merge. Cache raw rows; the merger still applies the offset.

---

## Slice 4 — Rejection of unsupported data classes

### Step 10: Ensure the resolver rejects unsupported classes clearly
**Repo:** Finbot.

The Slice-1 resolver already rejects `LEVEL_2_ORDER_BOOK`, `TRADES`, etc. because
they are absent from `LiveDataCapability.available_data_classes`. This step only
adds: (a) richer rejection messages (name the data class + suggest a proxy if
`MetricResolutionPath` offers one), and (b) tests for each unsupported class.

**File (new):** `tests/test_domain/test_live_capability_rejection.py`

**Verify:** `python -m pytest tests/test_domain/test_live_capability_rejection.py -q`

---

## Final review
```bash
# Finbot
ruff check finbot tests
black finbot tests
python -m pytest tests -q
# Package (after Slice 2 extraction)
cd C:/HAL/Github/finbar/packages/strategy-runtime && python -m pytest tests -q
# Finbar (still green against extracted merge)
cd C:/HAL/Github/finbar && python -m pytest tests -q
```

**Definition of Done:**
- [ ] `LiveCapabilityResolver` gates every live run before subscription.
- [ ] Derivatives merge is shared from the package (zero Finbar/Finbot copies).
- [ ] Finbot supplies funding + OI from Hyperliquid (Slice 2) and L-S/CVD/
      liquidations from CoinGlass when keyed (Slice 3).
- [ ] The same `(ohlcv, derivatives)` inputs yield identical signals in backtest
      and live (parity test green).
- [ ] Pure-OHLCV strategies run with zero external fetching and full parity.
- [ ] Unsupported data classes are rejected with a named, actionable reason.
