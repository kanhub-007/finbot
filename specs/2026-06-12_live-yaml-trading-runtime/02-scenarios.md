# Scenarios — Live YAML Trading Runtime

Scenarios are ordered by MoSCoW priority and implementation slice. Tests must use Classical-school, black-box style: real domain objects, in-memory fakes for boundaries, and outcome assertions.

---

### Scenario: Live-data dry-run processes closed candles without submitting orders
**Priority:** Must  
**Slice:** 1

**Gherkin:**
  Given a valid supported YAML strategy and a fake live market data stream
  And the warmup window contains enough closed historical bars
  When `finbot run --live-data` receives a new closed candle
  Then the runtime enriches the candle, evaluates the strategy, plans any order intent, persists the decision, and does not submit to the exchange

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| strategy_path | string | `tests/fixtures/strategies/amt_dip_buyer_final.yaml` | Required, readable, valid YAML |
| symbol | string | `BTC` | Required, non-empty |
| interval | string | `1h` | Supported Hyperliquid candle interval |
| mode | enum | `dry_run` | Must not submit orders |
| live_data | bool | `true` | Uses market stream |
| warmup_bars | list[dict] | OHLCV bars | Closed bars only, enough for strategy indicators |
| closed_candle | dict | OHLCV bar | Must represent a closed candle |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| runtime remains running until stopped | Fake event loop/process lifecycle |
| latest closed candle is enriched | Inspect persisted signal/audit event data |
| strategy evaluator returns HOLD/ENTRY/EXIT | Inspect returned/persisted decision |
| dry-run order intent is persisted when accepted | Inspect fake repository state |
| exchange submitted orders count is zero | Inspect fake exchange gateway state |

**Verify (Classical school, black-box):**
```python
fake_stream = FakeMarketDataStream()
fake_exchange = InMemoryExchangeGateway()
fake_repo = InMemoryBotStateRepository()
fake_bar_source = InMemoryBarSource(warmup_bars=closed_warmup_bars)

runtime = create_live_trading_runtime_use_case(
    stream=fake_stream,
    exchange=fake_exchange,
    repository=fake_repo,
    bar_source=fake_bar_source,
)

session = runtime.start(
    strategy_path="tests/fixtures/strategies/amt_dip_buyer_final.yaml",
    symbol="BTC",
    interval="1h",
    mode="dry_run",
)

fake_stream.emit_closed_candle(closed_candle_that_triggers_long_entry)
session.stop()

assert fake_repo.last_signal().action.value in {"hold", "long_entry", "short_entry"}
assert fake_repo.order_intent_count() >= 0
assert fake_exchange.submitted_order_count == 0
# Do NOT: fake_exchange.submit_order.assert_not_called()
```

**Also test:**
- Empty strategy path -> rejected before subscribing
- Warmup not ready -> no strategy evaluation
- Duplicate closed candle -> no duplicate signal key
- Stale data event -> risk decision rejected

---

### Scenario: Supported YAML strategy is loaded into the real rule-based evaluator
**Priority:** Must  
**Slice:** 1

**Gherkin:**
  Given a supported Finbot YAML strategy file
  When the live runtime starts
  Then it loads the YAML into `StrategyDefinition`, validates compatibility, and constructs `RuleBasedStrategyEvaluator` instead of the placeholder evaluator

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| strategy_path | string | `amt_v2_vol_filter.yaml` | Required, readable |
| mode | enum | `dry_run` | `dry_run`, `testnet`, or `live` |
| symbol | string | `BTC` | Required |
| interval | string | `1h` | Must match primary timeframe or be compatible |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| YAML is parsed once at startup | Inspect fake loader count/state |
| compatibility result is valid | Inspect returned startup/session result |
| unsupported features reject startup | Returned result has status `rejected` |
| placeholder `FinbarStrategyEvaluator` is not in the live path | Factory/integration outcome uses real evaluator behaviour |

**Verify (Classical school, black-box):**
```python
fake_stream = FakeMarketDataStream()
fake_repo = InMemoryBotStateRepository()
runtime = create_runtime_with_fakes(stream=fake_stream, repository=fake_repo)

result = runtime.start_once_for_test(
    strategy_path="tests/fixtures/strategies/amt_v2_vol_filter.yaml",
    symbol="BTC",
    interval="1h",
    mode="dry_run",
)

assert result.status == "running"
assert result.strategy_name
assert result.compatibility_valid is True
# A bar matching the strategy should not always return HOLD.
fake_stream.emit_closed_candle(closed_candle_that_triggers_known_entry)
assert fake_repo.last_signal().action.value != "hold"
# Do NOT: assert runtime._evaluator.__class__.__name__ == "RuleBasedStrategyEvaluator"
```

**Also test:**
- Unsupported indicator -> startup rejected before websocket subscription
- Unsupported operator -> startup rejected before websocket subscription
- Missing stop loss in live mode -> startup rejected
- Both target YAML fixtures start successfully in dry-run

---

### Scenario: Live candles are enriched with strategy-required indicators
**Priority:** Must  
**Slice:** 1

**Gherkin:**
  Given a YAML strategy with required indicator columns
  And a warmup window containing historical closed OHLCV bars
  When a new closed candle arrives
  Then the runtime appends it to the window, computes indicator columns, and evaluates the strategy using the latest enriched bar

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| warmup_bars | list[dict] | 200 OHLCV bars | Sorted or sortable by timestamp |
| closed_candle | dict | OHLCV bar | New timestamp, closed only |
| required_indicators | list[string] | `atr`, `vp_vah`, `vp_val` | Derived from strategy definition |
| min_bars | int | `100` | Must be > 0 |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| warmup contains the new candle | Inspect fake/in-memory warmup service output |
| latest bar includes required columns | Inspect persisted signal event enriched fields or returned processing result |
| latest bar passes enrichment validation before evaluation | Inspect `CandleProcessingResult.enrichment_valid == True` |
| evaluator is skipped until warmup ready | Signal count remains zero before readiness |
| gap/out-of-order candle is ignored or rejected safely | Inspect risk/audit event |

**Verify (Classical school, black-box):**
```python
fake_repo = InMemoryBotStateRepository()
fake_stream = FakeMarketDataStream()
fake_indicator_engine = InMemoryIndicatorEngine(required_columns={
    "atr": 10.0,
    "vp_vah": 52000.0,
    "vp_val": 50000.0,
    "acceptance_into_value": True,
})

runtime = create_runtime_with_fakes(
    stream=fake_stream,
    repository=fake_repo,
    indicator_engine=fake_indicator_engine,
    warmup_bars=closed_warmup_bars,
)
runtime.start_once_for_test(strategy_path=AMT_DIP, symbol="BTC", interval="1h", mode="dry_run")

fake_stream.emit_closed_candle(new_closed_candle)

signal = fake_repo.last_signal()
assert signal is not None
assert signal.candle_timestamp == new_closed_candle["timestamp"]
assert fake_repo.last_audit_event().event_type in {"signal_evaluated", "risk_decision"}
# Do NOT: fake_indicator_engine.calculate.assert_called_once()
```

**Also test:**
- Empty historical bar source -> startup rejected with warmup error
- Duplicate timestamp -> only one signal key persisted
- Missing required enriched column -> risk/audit event explains rejection
- Latest required indicator value is NaN -> candle rejected before strategy evaluation
- Latest required indicator value is inf/-inf -> candle rejected before strategy evaluation
- Out-of-order candle -> ignored without evaluating strategy

---

### Scenario: Invalid enriched candle is blocked before strategy evaluation
**Priority:** Must  
**Slice:** 1

**Gherkin:**
  Given a closed candle has been appended to a ready warmup window
  And the indicator engine returns an enriched latest bar
  When the enriched latest bar is missing required strategy columns or contains non-finite values
  Then the runtime records an enrichment validation rejection and does not evaluate the strategy or plan orders

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| enriched_bar | dict | `{"close": 50000, "atr": NaN}` | Must include every required strategy column with finite values |
| required_columns | set[string] | `{ "atr", "vp_vah", "vp_val", "acceptance_into_value" }` | Derived from parsed strategy definition |
| warmup_ready | bool | `true` | Must be true before validation is meaningful |
| has_gap | bool | `false` | Must be false to allow evaluation |
| candle_closed | bool | `true` | Partial candles must never reach evaluation |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| validation result is rejected | Inspect `CandleProcessingResult.enrichment_valid == False` |
| rejection reason names missing/non-finite columns | Inspect result/audit event reason |
| no strategy signal is persisted | Inspect fake repository signal count |
| no order intent is planned | Inspect fake repository order intent count |
| no exchange submission occurs | Inspect fake exchange submitted count |

**Verify (Classical school, black-box):**
```python
repo = InMemoryBotStateRepository()
fake_exchange = InMemoryExchangeGateway()
fake_indicator_engine = InMemoryIndicatorEngine(latest_bar={
    "timestamp": 1735689600,
    "open": 50000.0,
    "high": 51000.0,
    "low": 49000.0,
    "close": 50500.0,
    "atr": float("nan"),
    # vp_vah intentionally missing
})
runtime = create_runtime_with_fakes(
    repository=repo,
    exchange=fake_exchange,
    indicator_engine=fake_indicator_engine,
    warmup_bars=closed_warmup_bars,
)

result = runtime.process_closed_candle(new_closed_candle)

assert result.enrichment_valid is False
assert "atr" in result.enrichment_errors
assert "vp_vah" in result.enrichment_errors
assert repo.signal_count() == 0
assert repo.order_intent_count() == 0
assert fake_exchange.submitted_order_count == 0
# Do NOT: fake_strategy_evaluator.evaluate.assert_not_called()
```

**Also test:**
- Missing required boolean indicator -> rejected
- Required value is `None` -> rejected
- Required value is string that cannot be parsed as number/bool -> rejected
- Optional/non-required NaN column does not block evaluation
- Validation rejection is persisted as an audit/risk event with candle timestamp

---

### Scenario: Dry-run simulates position state and prevents duplicate orders
**Priority:** Must  
**Slice:** 2

**Gherkin:**
  Given dry-run mode and a signal that passes risk gates
  When the runtime processes the signal
  Then it persists a dry-run order intent, updates simulated position state, and marks the signal key as processed so restart cannot duplicate it

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| signal | SignalDecision | `LONG_ENTRY` | Must include symbol, interval, candle timestamp, strategy hash |
| mode | enum | `dry_run` | Never submits to exchange |
| current_position | PositionSnapshot | flat | From fake/simulated state |
| risk_config | BotConfig | max position USD | Positive limits |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| processed signal key is saved | Inspect fake repository |
| dry-run order intent is saved | Inspect fake repository |
| simulated position changes after accepted entry | Query runtime/fake exchange position |
| replaying same signal after restart is rejected as duplicate | New runtime with same repository rejects duplicate |

**Verify (Classical school, black-box):**
```python
repo = InMemoryBotStateRepository()
fake_exchange = DryRunExchangeGateway()
runtime = create_runtime_with_fakes(repository=repo, exchange=fake_exchange)

runtime.process_closed_enriched_bar(enriched_bar_that_triggers_long_entry)
first_intent_count = repo.order_intent_count()

runtime_after_restart = create_runtime_with_fakes(repository=repo, exchange=fake_exchange)
runtime_after_restart.process_closed_enriched_bar(enriched_bar_that_triggers_long_entry)

assert first_intent_count == 1
assert repo.order_intent_count() == 1
assert repo.last_risk_event().reason == "duplicate_signal"
assert fake_exchange.get_position("BTC").size > 0
# Do NOT: duplicate_gate.evaluate.assert_called_once()
```

**Also test:**
- Max position exceeded -> risk rejected, no intent saved
- Stale data -> risk rejected, no intent saved
- Exit signal creates reduce-only dry-run intent
- HOLD signal creates no order intent

---

### Scenario: Testnet submits normalized accepted intents with idempotent cloid
**Priority:** Must  
**Slice:** 3

**Gherkin:**
  Given testnet mode, private key configuration, market metadata, and an accepted order intent
  When the runtime processes the intent
  Then it normalizes size/price, submits to Hyperliquid testnet with `cloid`, persists the response, and reconciles state

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| mode | enum | `testnet` | Requires private key |
| private_key | SecretStr | `0x...` | Valid 64-byte hex key |
| market_metadata | MarketMetadata | BTC decimals/tick | Must exist for symbol |
| order_intent | OrderIntent | long entry | Must have positive Decimal size and cloid |
| base_url | string | Hyperliquid testnet URL | Must be testnet for this scenario |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| normalized intent uses valid size/price | Inspect persisted intent/response |
| exchange response is persisted | Inspect repository |
| retry requires cloid | Missing cloid produces non-retryable error |
| reconciliation record is saved | Inspect repository |

**Verify (Classical school, black-box):**
```python
repo = InMemoryBotStateRepository()
fake_gateway = FakeExchangeGateway()
fake_metadata = InMemoryMarketMetadataProvider.for_btc()
runtime = create_runtime_with_fakes(
    repository=repo,
    exchange=fake_gateway,
    metadata_provider=fake_metadata,
    mode="testnet",
)

runtime.process_closed_enriched_bar(enriched_bar_that_triggers_long_entry)

intent = repo.last_order_intent()
response = repo.last_order_response()
assert intent.cloid
assert intent.size > Decimal("0")
assert response.status in {"ok", "resting", "filled", "accepted"}
assert repo.last_reconciliation() is not None
# Do NOT: fake_gateway.submit_order.assert_called_once_with(intent)
```

**Also test:**
- Missing private key -> startup rejected
- Unknown symbol metadata -> order rejected before submit
- Missing cloid -> no retry and non-retryable failure persisted
- Exchange rejection -> lifecycle becomes rejected and is visible in status

---

### Scenario: Account websocket events update order lifecycle and fills
**Priority:** Should  
**Slice:** 4

**Gherkin:**
  Given the runtime has submitted an order
  When Hyperliquid account websocket events report order updates or fills
  Then the runtime updates order lifecycle, persists fills, and blocks unsafe new orders if reconciliation is unknown

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| order_update_event | dict | accepted/open/cancelled/rejected | Must contain order id or cloid |
| fill_event | dict | fill size/price/fee | Must map to known order or require reconcile |
| lifecycle_state | enum | `submitted` | Existing lifecycle state |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| accepted update moves lifecycle to accepted/open | Inspect repository lifecycle state |
| partial fill persists fill and remaining size | Inspect repository fill records |
| duplicate fill update is idempotent | Fill count does not increase |
| unknown update moves to unknown reconciliation required | Inspect lifecycle state and risk blocker |

**Verify (Classical school, black-box):**
```python
repo = InMemoryBotStateRepository()
runtime = create_runtime_with_fakes(repository=repo)
intent_id = repo.record_order_intent(sample_submitted_intent)

runtime.process_account_event(order_update_open_for(intent_id))
runtime.process_account_event(partial_fill_for(intent_id, size=Decimal("0.01")))
runtime.process_account_event(partial_fill_for(intent_id, size=Decimal("0.01")))

assert repo.order_lifecycle(intent_id).state.value in {"open", "partially_filled"}
assert repo.fill_count_for_intent(intent_id) == 1
# Do NOT: repository.record_fill.assert_called_once()
```

**Also test:**
- Rejected update marks lifecycle rejected
- Cancelled update marks lifecycle cancelled
- Unknown order update blocks new order planning
- Queue-full policy never drops account/order/fill events silently

---

### Scenario: Live mode starts only after all safety gates pass
**Priority:** Must  
**Slice:** 5

**Gherkin:**
  Given the operator requests live mode
  When Finbot checks live-mode gates
  Then it starts only if explicit acknowledgment, secrets, persistence, reconciliation, risk limits, and strategy compatibility all pass

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| FINBOT_MODE | env string | `live` | Must be exactly `live` |
| FINBOT_LIVE_TRADING_ACK | env string | `true` | Required |
| private_key | SecretStr | `0x...` | Required and valid |
| db_path | string | `data/finbot.db` | Durable SQLite path required |
| max_position_usd | Decimal | `100` | Positive and intentionally small at first |
| max_daily_loss_usd | Decimal | `25` | Positive |
| startup_reconciliation | SafetyValidation | success | Required before first signal |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| all blockers are returned together if live cannot start | Inspect `LiveModeGuard` result |
| no websocket subscription happens when blockers exist | Fake stream remains unsubscribed |
| live session starts only after all blockers are gone | Returned session status is running |
| live order notional is bounded by config | Inspect planned intent size/notional |

**Verify (Classical school, black-box):**
```python
settings = live_settings(
    ack=False,
    private_key="",
    db_path=":memory:",
    max_position_usd=Decimal("0"),
)
fake_stream = FakeMarketDataStream()
runtime = create_runtime_with_fakes(stream=fake_stream, settings=settings)

result = runtime.start_live(strategy_path=AMT_DIP, symbol="BTC", interval="1h")

assert result.status == "rejected"
assert "FINBOT_LIVE_TRADING_ACK" in result.message
assert "private key" in result.message
assert "durable persistence" in result.message
assert fake_stream.subscription_count == 0
# Do NOT: live_guard.check_live_mode.assert_called_once()
```

**Also test:**
- Mainnet with `mode != live` -> rejected
- Live with unsupported YAML feature -> rejected
- Live with unknown reconciliation state -> rejected
- Live first-run tiny notional cap is enforced
