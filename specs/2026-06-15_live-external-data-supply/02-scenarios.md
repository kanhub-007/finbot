# Scenarios — Live External Data Supply

Scenarios use Classical-school, black-box tests with in-memory fakes for
streams, repositories, gateways, and (new) external-data sources. They assert on
**outcomes** (returned values / observable state), never on which internal
methods were called.

Fixture strategies live in `tests/fixtures/strategies/`. Where a scenario needs
an external-data strategy fixture that does not yet exist, create it as part of
the slice.

Scenarios are ordered so each slice is independently shippable.

---

## Slice 1 — Capability-aware gating (no new data fetching yet)

### Scenario: Finbot reports, per strategy, which data classes it can supply live
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a parsed strategy definition and the package metric catalog
  When Finbot checks live compatibility
  Then it reports every metric's required data class and whether Finbot can supply it, and rejects the run (before websocket subscription) when any required class is unsupplied with no acceptable proxy

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| strategy_path | path | `derivatives_funding.yaml` | Uses `funding_rate` indicator |
| available_data_classes | set[DataClass] | `{INTRADAY_OHLCV, DERIVATIVES}` | Finbot's declared live supply |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| A pure-OHLCV strategy is reported fully supported | compatibility result lists no missing data classes |
| A strategy needing `LEVEL_2_ORDER_BOOK` is rejected with the named class | compatibility result blocker |
| A strategy needing `DERIVATIVES` (not yet wired at Slice 1) is rejected until Slice 2 | blocker names `derivatives` |
| Finbot never subscribes to market data for a rejected strategy | fake stream `subscribe_count == 0` |

**Verify (Classical school, black-box):**
```python
from finbot.core.domain.services.live_capability_resolver import (
    LiveCapabilityResolver,
)
from finbar_strategy_runtime.domain.entities.data_class import DataClass

resolver = LiveCapabilityResolver(
    available_data_classes={DataClass.INTRADAY_OHLCV},
)
report = resolver.resolve(definition=ohlcv_strategy_definition)

assert report.supported is True
assert report.missing == []

report2 = resolver.resolve(definition=derivatives_strategy_definition)
assert report2.supported is False
assert DataClass.DERIVATIVES in report2.missing
```

**Also test:**
- A conceptual metric (e.g. `volatility`) with a proxy path on OHLCV resolves via the proxy when the actual path needs unavailable data.
- Unknown metric name -> rejected with the name (not silently dropped).
- The report is persisted to the startup audit log.

---

## Slice 2 — Derivatives data supply (the achievable now-tier)

### Scenario: A derivatives strategy backtests in Finbar and live-trades in Finbot identically
**Priority:** Must
**Slice:** 2

**Gherkin:**
  Given a strategy that uses funding rate and/or open interest
  When the same enriched bars are fed to the package evaluator in both contexts
  Then both produce identical signals, because Finbot merges the same derivatives columns with the same no-lookahead offset as Finbar

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| strategy_path | path | `derivatives_funding.yaml` | schema 2.0, uses `funding_rate` and/or `open_interest` |
| interval | string | `1h` | Must be parseable by package `interval_offset` |
| derivatives_rows | list[DerivativesMetrics] | funding/OI points | Timestamped; merged as-of with one-interval offset |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Finbot's merged frame contains `funding_rate` / `open_interest` columns | Inspect enriched frame columns |
| A bar whose derivatives value is not yet available (lookahead) reads `NaN` | Parity test vs package merge offset |
| A bar whose derivatives value is available reads the value, not NaN | Inspect latest bar dict |
| Identical enriched bars -> identical `SignalDecision.action` in backtest and live | Cross-context parity test |

**Verify (Classical school, black-box):**
```python
derivatives_source = InMemoryDerivativesSource(rows=funding_and_oi_rows)
runtime = create_live_runtime_with_fakes(
    external_data_sources={"derivatives": derivatives_source},
)
runtime.start(strategy_path=DERIVATIVES_STRAT, symbol="BTC", interval="1h")

result = runtime.process_closed_candle(closed_candle_where_funding_is_high)

assert result.enrichment_valid is True
assert result.signal_action in ("short_entry", "hold")  # whatever the strategy says
```

**Also test:**
- Derivatives source returns no rows -> columns present but all `NaN`; strategy HODLs (no crash, no false signal).
- A duplicate derivatives timestamp -> last value wins (matches package dedup).
- Derivatives available only after T+interval -> bar at T sees `NaN`, bar at T+interval sees the value (no-lookahead invariant).

---

### Scenario: Derivatives columns come from a no-lookahead merge shared with Finbar
**Priority:** Must
**Slice:** 2

**Gherkin:**
  Given Finbot needs to attach derivatives columns to the live OHLCV frame
  When it enriches a bar
  Then it calls the same package merge function Finbar's backtest uses, so the offset, NaN handling, and timezone normalisation are identical

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| merge_fn | callable | package `merge_derivatives_asof` | Single source of truth |
| ohlcv_frame | DataFrame | live warmup frame | DatetimeIndex |
| derivatives_rows | list[DerivativesMetrics] | provider rows | Timestamped |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Finbot imports `merge_derivatives_asof` from the package, not a local copy | architecture/import test |
| Result equals the package's own output for the same inputs | direct call comparison |
| Offset matches `interval_offset(interval)` exactly | inspect availability timestamps |

**Verify (Classical school, black-box):**
```python
from finbar_strategy_runtime.indicators.derivatives_merge import (  # extracted in Slice 2
    merge_derivatives_asof,
)

merged = merge_derivatives_asof(ohlcv_frame, derivatives_rows, interval="1h")
assert "funding_rate" in merged.columns
# The bar at the derivatives timestamp itself must NOT see the value.
assert pd.isna(merged.loc[at_timestamp, "funding_rate"])
```

**Also test:**
- Multiple intervals (`5m`, `1h`, `1d`, `1w`) produce the correct offset.
- Empty derivatives list -> all requested columns present as `NaN` (Invariant #2 from the package: column always exists).

---

### Scenario: Finbot fetches live derivatives from Hyperliquid REST
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given a live/testnet Finbot session running a derivatives strategy
  When the runtime needs derivatives history for warmup
  Then Finbot fetches funding + open interest from Hyperliquid (`info.funding_history`, `meta_and_asset_ctxs`) into the `DerivativesMetrics` shape, with no secrets and no CoinGlass key required

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| symbol | string | `BTC` | Plain coin name for funding_history |
| interval | string | `1h` | Informational for funding cadence |
| provider | enum | `hyperliquid` | Free, no API key |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| `funding_rate` and `open_interest` rows are populated | Inspect fetched rows |
| Fetch failures degrade gracefully (empty rows -> NaN columns) | No exception, strategy HODLs |
| No API key or secret is required for Hyperliquid funding/OI | Config check |

**Verify (Classical school, black-box):**
```python
source = HyperliquidDerivativesSource(base_url=TESTNET_URL)
rows = source.fetch_recent(symbol="BTC", interval="1h", count=200)

assert any(r.funding_rate is not None for r in rows)
assert all(r.symbol == "BTC" for r in rows)
```

**Also test:**
- HIP-3 / `dex:COIN` symbols resolve to the plain coin name for funding.
- Network error -> returns `[]` (runtime warms up with NaN columns, no crash).

---

## Slice 3 — L/S ratio, CVD, liquidations (CoinGlass-backed) + resilience

### Scenario: Optional CoinGlass-backed metrics are supplied when a key is configured
**Priority:** Could
**Slice:** 3

**Gherkin:**
  Given a strategy using long/short ratio, cumulative volume delta, or liquidations
  And a CoinGlass API key is configured
  When Finbot enriches a bar
  Then those columns are fetched and merged with the same no-lookahead discipline; when no key is configured, the columns are absent and the strategy is rejected by capability gating unless a proxy path exists

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| coinglass_api_key | secret | env `COINGLASS_API_KEY` | Optional |
| metrics | list | `long_short_ratio`, `cumulative_volume_delta`, `liquidations_long_1h` | Subset of `DERIVATIVES_FIELDS` |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| With key: requested columns populated | Inspect merged frame |
| Without key: capability resolver reports `DERIVATIVES` partially supplied and rejects strategies whose required metric has no proxy | Compatibility result |

**Verify (Classical school, black-box):**
```python
source = CoinGlassDerivativesSource(api_key=key or None)
rows = source.fetch_recent(symbol="BTC", interval="1h", count=200)
if key:
    assert any(r.long_short_ratio is not None for r in rows)
else:
    assert rows == [] or all(r.long_short_ratio is None for r in rows)
```

**Also test:**
- Rate-limit / 429 response -> back off then degrade to empty rows.
- Stale key -> empty rows, capability gating handles the rest.

---

### Scenario: External data is optional per-strategy, never mandatory infrastructure
**Priority:** Should
**Slice:** 3

**Gherkin:**
  Given Finbot is configured with no external data sources at all
  When a pure-OHLCV strategy is started
  Then it runs with full parity and no external fetch is attempted

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| external_data_sources | dict | `{}` | Empty wiring |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| No network call to funding/OI/CoinGlass endpoints | Fake/instrumented sources record zero calls |
| OHLCV-only strategy still trades normally | Existing live-runtime tests pass |

**Verify (Classical school, black-box):**
```python
runtime = create_live_runtime_with_fakes(external_data_sources={})
result = runtime.process_closed_candle(closed_candle_that_triggers_long_entry)
assert result.signal_action == "long_entry"
```

**Also test:**
- A derivatives strategy started with no derivatives source -> rejected at compatibility gate, not at enrichment time.

---

## Slice 4 — Finer data classes (documented, not built this iteration)

### Scenario: Strategies requiring unsupported data classes are rejected with a clear reason
**Priority:** Could
**Slice:** 4

**Gherkin:**
  Given a strategy that requires `LEVEL_2_ORDER_BOOK`, `TRADES`, or `ORDER_BOOK_EVENTS`
  When Finbot checks compatibility
  Then it rejects the run before subscription with a human-readable reason naming the data class and (if known) a proxy alternative

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| required_data_class | DataClass | `LEVEL_2_ORDER_BOOK` | Not in Finbot's support tiers |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Run rejected | `start_live` returns `status="rejected"` |
| Reason names the data class | Inspect rejection message |
| No websocket subscription attempted | fake stream `subscribe_count == 0` |

**Verify (Classical school, black-box):**
```python
report = resolver.resolve(definition=l2_book_strategy_definition)
assert report.supported is False
assert DataClass.LEVEL_2_ORDER_BOOK in report.missing
```

**Also test:**
- A microstructure metric that has an OHLCV proxy path is accepted via the proxy (not rejected outright).

> Slice 4 is intentionally rejection-only. Building a live L2/trades feed is a
> large, separate effort; this slice simply guarantees such strategies fail
> fast and clearly instead of silently HODLing.
