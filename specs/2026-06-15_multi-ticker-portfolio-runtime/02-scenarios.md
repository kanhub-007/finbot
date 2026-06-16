# Scenarios — Multi-Ticker Portfolio Runtime

Scenarios are ordered by MoSCoW priority and grouped into Slices. Each
scenario has Gherkin, an input table, expected state, and a Classical-school
black-box Verify block using in-memory fakes at the boundaries.

**Conventions for Verify blocks (per AGENTS.md §3):**

- Use real domain objects and `InMemoryBotStateRepository` / fake exchange
  gateways. Never mock domain entities.
- Assert on **outcomes** (returned results, persisted state, exchange calls
  received). Never `assert_called` / `verify()` on domain interfaces.
- A fake exchange records submitted intents in a list; tests assert on that
  list's contents.

---

# Slice 1 — MVP (all Must)

Proves: one strategy runs across N symbols in one process, with a portfolio
risk budget, per-symbol idempotency, multi-symbol reconciliation, durable
positions, and a portfolio kill switch.

---

### Scenario S1: Start a multi-symbol runtime with a static symbol set
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a strategy file and a configured symbol set ["BTC", "ETH", "SOL"]
  When  the operator starts the portfolio runtime in dry_run mode
  Then  one BotRun is created covering all three symbols
  And   a SymbolPipeline is initialised for each symbol
  And   each pipeline subscribes to its symbol's candle stream
  And   the runtime reports status "running" with the full symbol set

**Input table:**
| Field          | Type   | Example                          | Constraints                    |
|----------------|--------|----------------------------------|--------------------------------|
| strategy_path  | str    | "strategies/amt_dip_buyer.yaml"  | Required, existing file        |
| symbols        | list   | ["BTC", "ETH", "SOL"]            | Required, non-empty, deduped   |
| interval       | str    | "1h"                             | Required, one interval for all |
| mode           | str    | "dry_run"                        | dry_run | testnet | live  |
| warmup_bars    | int    | 100                              | > 0                            |

**Expected output / state change:**
| Assertion                                          | How to verify                              |
|----------------------------------------------------|--------------------------------------------|
| Exactly one BotRun created                         | `repo.get_latest_bot_run()` is not None    |
| BotRun.symbol is "BTC,ETH,SOL" (or joined set)     | Inspect BotRun                             |
| Three SymbolPipeline instances exist               | Runtime exposes `active_symbols()`         |
| Each symbol has an open subscription               | Fake stream records 3 subscribe calls      |

**Verify (Classical school, black-box):**
```python
fake_stream = FakeMarketDataStream()
fake_exchange = FakeExchangeGateway()  # records submit_order calls
repo = InMemoryBotStateRepository()

runtime = PortfolioTradingRuntimeUseCase(
    symbol_pipelines=build_pipelines(  # factory wires evaluator per symbol
        symbols=["BTC", "ETH", "SOL"], interval="1h",
        strategy_path="strategies/amt_dip_buyer.yaml",
        stream=fake_stream, exchange=fake_exchange, repo=repo,
    ),
    exchange=fake_exchange, repo=repo, mode=TradingMode.DRY_RUN,
)
runtime.start(strategy_path="strategies/amt_dip_buyer.yaml",
              symbols=["BTC", "ETH", "SOL"], interval="1h")

assert runtime.is_running()
assert set(runtime.active_symbols()) == {"BTC", "ETH", "SOL"}
assert fake_stream.subscribed_symbols == {"BTC", "ETH", "SOL"}
run = repo.get_latest_bot_run()
assert run is not None and run.mode == "dry_run"
```

**Also test:**
- symbols contains a duplicate, e.g. ["BTC", "BTC", "ETH"] → deduped to {"BTC", "ETH"}
- symbols contains lower/upper mix → normalised (decision: case-insensitive, upper-cased)
- interval mismatch across symbols → not supported in MVP; single interval only

---

### Scenario S2: Per-symbol candle demux and independent warmup
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the portfolio runtime is running for ["BTC", "ETH"]
  When  a closed candle arrives for ETH before BTC's warmup is ready
  Then  only ETH's pipeline processes the candle
  And   BTC's pipeline ignores it (its warmup is still filling)
  And   BTC and ETH maintain independent warmup windows and enriched frames

**Input table:**
| Field        | Type | Example                    | Constraints              |
|--------------|------|----------------------------|--------------------------|
| candle event | dict | {"symbol": "ETH", "close": | Must carry a symbol tag  |
|              |      |  3000, "timestamp": ...}   | or arrive via demux      |

**Expected output / state change:**
| Assertion                                            | How to verify                       |
|------------------------------------------------------|-------------------------------------|
| BTC warmup count unchanged by ETH candle             | Inspect BTC pipeline warmup count   |
| ETH warmup count incremented                         | Inspect ETH pipeline warmup count   |
| BTC enriched frame is None / stale                   | Pipeline reports `is_ready()` False |

**Verify:**
```python
btc_pipe = fake_pipelines["BTC"]
eth_pipe = fake_pipelines["ETH"]

# BTC needs 100 bars, has received 5
runtime.process_closed_candle("ETH", eth_candle())

assert eth_pipe.warmup_count == 6
assert btc_pipe.warmup_count == 5      # untouched by ETH's candle
assert btc_pipe.is_ready() is False
assert btc_pipe.enriched_frame is None
```

**Also test:**
- candle for an unknown symbol → logged + dropped (never KeyError)
- candle missing symbol tag and no demux arg → logged + dropped

---

### Scenario S3: Portfolio MaxOpenPositionsGate blocks new entries
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given max_open_positions = 2 and two positions are open (BTC long, ETH short)
  When  SOL produces a LONG_ENTRY signal
  Then  the portfolio gate rejects the entry
  And   a risk event "rejected / max_open_positions" is persisted
  And   no order intent is recorded for SOL
  And   the BTC/ETH positions are unaffected

**Input table:**
| Field                      | Type    | Example | Constraints     |
|----------------------------|---------|---------|-----------------|
| max_open_positions         | int     | 2       | > 0             |
| portfolio_open_positions   | int     | 2       | read from repo  |

**Expected output / state change:**
| Assertion                                          | How to verify                              |
|----------------------------------------------------|--------------------------------------------|
| SOL signal rejected by max_open_positions          | RiskEventRecord decision="rejected"        |
| No OrderIntent for SOL                             | No intent with symbol="SOL" in repo        |
| Open BTC/ETH trades unchanged                      | repo.open_trades() still has BTC, ETH      |

**Verify:**
```python
repo = InMemoryBotStateRepository()
# Seed two open trades
repo.open_trade(Trade(symbol="BTC", side=PositionDirection.LONG, ...))
repo.open_trade(Trade(symbol="ETH", side=PositionDirection.SHORT, ...))

gate = MaxOpenPositionsGate(max_positions=2)
signal = SignalDecision(action=SignalAction.LONG_ENTRY, symbol="SOL", ...)
ctx = {"portfolio_open_position_count": repo.count_open_trades()}  # = 2

decision = gate.check(signal, ctx)

assert decision.accepted is False
assert decision.gate_name == "max_open_positions"
# Outcome only — never assert gate.check was called N times.
```

**Also test:**
- max_open_positions = 0 → gate disabled (passes through), documented as "unlimited"
- 1 open position, max 2 → new entry accepted
- exit signal (LONG_EXIT) never blocked by this gate (exits reduce count)

---

### Scenario S4: Portfolio MaxGrossNotionalGate blocks oversized book
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given max_gross_notional_usd = 500 and open positions sum to 450 USD notional
  When  a new entry of notional 100 USD is proposed
  Then  the gate rejects it because 450 + 100 = 550 > 500
  And   a risk event "rejected / max_gross_notional" is persisted

**Input table:**
| Field                          | Type    | Example | Constraints          |
|--------------------------------|---------|---------|----------------------|
| max_gross_notional_usd         | Decimal | 500     | > 0                  |
| portfolio_gross_notional_usd   | Decimal | 450     | sum of |size*price|  |
| proposed_notional_usd          | Decimal | 100     | from proposed intent |

**Verify:**
```python
gate = MaxGrossNotionalGate(max_gross_usd=Decimal("500"))
signal = SignalDecision(action=SignalAction.LONG_ENTRY, symbol="BTC", ...)
ctx = {
    "portfolio_gross_notional_usd": Decimal("450"),
    "proposed_notional_usd": Decimal("100"),
}
assert gate.check(signal, ctx).accepted is False

# An entry that fits is accepted
ctx["proposed_notional_usd"] = Decimal("40")
assert gate.check(signal, ctx).accepted is True
```

**Also test:**
- gross notional uses absolute value (a short counts as positive exposure)
- exit signals bypass the gross cap (exits reduce exposure)

---

### Scenario S5: Per-symbol idempotency holds across the portfolio
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the same closed candle is delivered twice for BTC (replay/reconnect)
  When  the duplicate candle is processed
  Then  the signal_key (symbol:interval:ts:strategy_hash) is already marked processed
  And   no second order is created for BTC
  And   ETH/SOL processing is unaffected

**Verify:**
```python
# First delivery
runtime.process_closed_candle("BTC", btc_candle_at_ts(1000))
assert len(fake_exchange.submitted) == 1

# Duplicate delivery of the same closed candle
runtime.process_closed_candle("BTC", btc_candle_at_ts(1000))
assert len(fake_exchange.submitted) == 1   # still one — idempotent

# A genuinely new candle still proceeds
runtime.process_closed_candle("BTC", btc_candle_at_ts(2000))
assert len(fake_exchange.submitted) == 2
```

**Also test:**
- same candle timestamp for ETH (different symbol) is NOT a duplicate — proceeds
- reconnect storm replays last 5 candles → at most the newest creates an order

> **Note:** `SignalDecision.signal_key` already embeds `symbol`, so no change to
> the key scheme is required — only that the dedup check runs per pipeline.

---

### Scenario S6: Reconcile all symbols on startup
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the runtime restarts with symbols ["BTC", "ETH"] and a prior open BTC position
  When  startup reconciliation runs
  Then  positions AND open orders are fetched for every symbol
  And   a Trade is reconstructed for the open BTC position
  And   any exchange order unknown to the DB is flagged in an audit log
  And   any DB order missing from the exchange is flagged (stale DB)

**Verify:**
```python
fake_exchange.positions = {
    "BTC": PositionSnapshot(symbol="BTC", direction=PositionDirection.LONG, size=Decimal("0.5")),
    "ETH": PositionSnapshot(symbol="ETH", direction=PositionDirection.FLAT, size=Decimal("0")),
}
fake_exchange.open_orders = {"BTC": [...], "ETH": []}

recs = runtime.reconcile_on_startup(symbols=["BTC", "ETH"])

assert {r.symbol for r in recs} == {"BTC", "ETH"}
btc_rec = next(r for r in recs if r.symbol == "BTC")
assert btc_rec.exchange_has_position is True
# A Trade was reconstructed for the open BTC position
assert repo.count_open_trades() == 1
assert repo.open_trades()[0].symbol == "BTC"
# Reconciliation result persisted
assert repo.list_reconciliations()
```

**Also test:**
- exchange has a position for a symbol NOT in the set → flagged, not auto-closed
- DB records an open order the exchange no longer shows → flagged stale
- reconciliation failure for one symbol does not abort reconciliation of others

---

### Scenario S7: Durable Trade entity opened and closed
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given BTC has no open position
  When  a LONG_ENTRY signal is accepted and the order fills
  Then  a Trade is opened with side=long, entry_price, opened_at, strategy_hash
  And   it is persisted as status="open"
  When  a later LONG_EXIT signal fills
  Then  the same Trade is updated to status="closed" with close_price, closed_at, realized_pnl

**Input/Output:**
| Event        | Trade field changes                                        |
|--------------|------------------------------------------------------------|
| entry fill   | opened, opened_at=now, entry_price=fill, size=fill size    |
| exit fill    | status="closed", closed_at=now, close_price=fill, realized_pnl computed |

**Verify:**
```python
# Entry
runtime.process_closed_candle("BTC", entry_signal_candle())
fake_exchange.simulate_fill(symbol="BTC", side="buy", size=Decimal("0.1"),
                            price=Decimal("50000"))

trades = repo.open_trades()
assert len(trades) == 1
t = trades[0]
assert t.symbol == "BTC" and t.side == PositionDirection.LONG
assert t.status == "open"
assert t.entry_price == Decimal("50000")

# Exit
runtime.process_closed_candle("BTC", exit_signal_candle())
fake_exchange.simulate_fill(symbol="BTC", side="sell", size=Decimal("0.1"),
                            price=Decimal("51000"))

closed = repo.closed_trades()
assert len(closed) == 1
assert closed[0].position_id == t.position_id
assert closed[0].status == "closed"
assert closed[0].realized_pnl == Decimal("100")   # (51000-50000)*0.1
```

**Also test:**
- partial fill → size reflects filled amount, status stays "open" until fully exited
- exit signal with no open trade → reduce-only gate rejects (existing behaviour)

---

### Scenario S8: Portfolio kill switch — cancel all and close all
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given open orders on BTC/ETH and an open SOL position
  When  the operator invokes the kill switch with cancel_all=true, close_all=false
  Then  every open order across all symbols is cancelled on the exchange
  And   the SOL position is left intact (close_all=false)
  When  the kill switch is invoked with close_all=true
  Then  every open position is market-closed reduce-only

**Verify:**
```python
fake_exchange.open_orders = {"BTC": [o1], "ETH": [o2]}
fake_exchange.positions = {"SOL": long_position(size=Decimal("5"))}

result = runtime.kill_switch(cancel_all=True, close_all=False)

assert fake_exchange.cancelled_orders == {o1.order_id, o2.order_id}
assert fake_exchange.closed_positions == []        # position untouched
assert result.orders_cancelled == 2
assert result.positions_closed == 0

result = runtime.kill_switch(cancel_all=True, close_all=True)
assert fake_exchange.closed_positions == ["SOL"]   # reduce-only market close
```

**Also test:**
- one symbol's cancel fails → others still attempted, failure reported per symbol
- kill switch is idempotent (calling twice does not error)

---

### Scenario S9: Empty symbol set rejected at startup
**Priority:** Must
**Slice:** 1 (edge / safety)

**Gherkin:**
  Given an empty symbol list
  When  the operator starts the runtime
  Then  startup is rejected with a clear message
  And   no BotRun is created and no subscriptions are made

**Verify:**
```python
result = runtime.start(strategy_path=..., symbols=[], interval="1h")
assert result.status == "rejected"
assert "symbol" in result.message.lower()
assert repo.get_latest_bot_run() is None
assert fake_stream.subscribed_symbols == set()
```

---

### Scenario S10: One symbol's stream failure is isolated
**Priority:** Must
**Slice:** 1 (edge / safety)

**Gherkin:**
  Given the runtime runs ["BTC", "ETH", "SOL"]
  When  ETH's websocket subscription errors / disconnects
  Then  ETH's pipeline logs the error and marks itself degraded
  And   BTC and SOL keep processing candles normally
  And   ETH's open position (if any) is still protected by reconciliation

**Verify:**
```python
fake_stream.fail_symbol("ETH")   # raises on ETH subscribe/receive

runtime.process_closed_candle("BTC", btc_candle())   # succeeds
runtime.process_closed_candle("SOL", sol_candle())   # succeeds

assert runtime.symbol_status("BTC") == "ok"
assert runtime.symbol_status("ETH") == "degraded"
# BTC/SOL processed despite ETH failure — no exception propagated
```

**Also test:**
- ETH recovers (reconnect) → status returns to "ok" and resumes processing
- ALL symbols fail → runtime status "degraded", operator notified, kill switch available

---

### Scenario S11: Portfolio full does not block exits
**Priority:** Must
**Slice:** 1 (edge / safety)

**Gherkin:**
  Given max_open_positions = 1 and one open BTC position (portfolio full)
  When  BTC produces a LONG_EXIT signal
  Then  the exit is accepted (exits bypass the open-position cap)
  And   the position is closed
  And   after close, a new entry elsewhere becomes possible

**Verify:**
```python
gate = MaxOpenPositionsGate(max_positions=1)
exit_signal = SignalDecision(action=SignalAction.LONG_EXIT, symbol="BTC", ...)
ctx = {"portfolio_open_position_count": 1}
assert gate.check(exit_signal, ctx).accepted is True   # exits bypass
```

**Also test:**
- SHORT_EXIT, LONG_EXIT, SHORT_EXIT all bypass open-position and gross-notional caps
- a NEW entry right after the exit fills is re-gated (portfolio now has room)

---

# Slice 2 — Should

Enhances resilience and efficiency without changing the core model.

---

### Scenario S12: Per-symbol "last candle seen" short-circuit
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given BTC's latest candle timestamp is unchanged since last analysis
  When  the pipeline receives the same candle again
  Then  enrichment/evaluation is skipped (no wasted indicator recompute)
  And   no new signal is produced
  And   the previously analyzed frame is reused

**Verify:**
```python
pipe = pipelines["BTC"]
pipe.process_candle(btc_candle(ts=1000))          # full analysis
n_first = indicator_calc.call_count

pipe.process_candle(btc_candle(ts=1000))          # same ts → skip
assert indicator_calc.call_count == n_first       # no recompute

pipe.process_candle(btc_candle(ts=2000))          # new ts → analyze
assert indicator_calc.call_count > n_first
```

---

### Scenario S13: Orphaned-exit safety — symbol with open trade stays active
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given the static symbol set is ["BTC", "ETH"] and BTC has an open position
  When  the symbol set is refreshed to ["ETH", "SOL"] (BTC dropped)
  Then  BTC remains in the ACTIVE set until its position is closed
  So that the exit signal for BTC can still be generated and the position is never orphaned

**Verify:**
```python
repo.open_trade(Trade(symbol="BTC", side=PositionDirection.LONG, ...))
runtime.refresh_symbol_set(["ETH", "SOL"])

active = runtime.active_symbols()
assert "BTC" in active            # kept alive because it has an open trade
assert {"ETH", "SOL"}.issubset(active)
```

**Also test:**
- once BTC's position closes, BTC is removed on next refresh

---

### Scenario S14: Batched warmup fetch via multi-symbol snapshot
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given a symbol set of N symbols needs warmup bars
  When  warmup is loaded
  Then  a single batched fetch is issued (Hyperliquid multi-symbol candle snapshot)
  And   each pipeline's warmup window is populated
  And   the number of network round-trips is O(1), not O(N)

**Verify:**
```python
fake_bar_source.batch_calls = 0
runtime.load_warmup(symbols=["BTC", "ETH", "SOL"], bars=100)

assert fake_bar_source.batch_calls == 1            # one batched call, not 3
for sym in ["BTC", "ETH", "SOL"]:
    assert pipelines[sym].warmup_count >= 100
```

---

### Scenario S15: Aggregated portfolio status snapshot
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given the runtime runs multiple symbols
  When  the operator requests portfolio status
  Then  a single snapshot returns per-symbol status plus portfolio totals
  And   totals include open_position_count, gross_notional_usd, open_order_count

**Verify:**
```python
snap = runtime.portfolio_status()
assert set(snap.symbols) == {"BTC", "ETH", "SOL"}
assert snap.portfolio_open_positions == repo.count_open_trades()
assert snap.portfolio_gross_notional_usd >= 0
# each per-symbol entry has warmup_ready, last_signal_action, position_direction
assert all("warmup_ready" in s for s in snap.per_symbol.values())
```

---

# Slice 3 — Could

Extend the model toward freqtrade-level flexibility. Interface seeds land in
Slice 1 so these are drop-ins, not rewrites.

---

### Scenario S16: Dynamic pairlist provider
**Priority:** Could
**Slice:** 3

**Gherkin:**
  Given a VolumePairlistProvider configured with min_quote_volume = 1_000_000
  When  the provider refreshes
  Then  it returns only symbols meeting the volume threshold
  And   the runtime adopts the new symbol set (subject to orphaned-exit safety)

**Verify:**
```python
provider = VolumePairlistProvider(min_quote_volume=1_000_000,
                                  market_data=fake_ticker_source)
syms = provider.symbols()
assert "BTC" in syms and "DUST" not in syms   # below threshold excluded
```

---

### Scenario S17: Cross-symbol informative data (MarketDataProvider)
**Priority:** Could
**Slice:** 3

**Gherkin:**
  Given a strategy that references an informative pair (e.g. BTC frame while trading ETH)
  When  ETH's pipeline enriches
  Then  it can read BTC's analyzed frame through the shared MarketDataProvider
  And   no lookahead bias is introduced (only closed BTC bars are visible)

**Verify:**
```python
provider = MarketDataProvider(bar_source, indicator_calc, bar_converter)
provider.refresh(["BTC", "ETH"])
eth_frame = provider.get_enriched("ETH", "1h")
btc_informative = provider.get_enriched("BTC", "1h")
assert btc_informative is not None
# The frame visible to ETH ends at or before ETH's current closed candle (no lookahead)
assert provider.last_timestamp("BTC") <= eth_current_closed_ts
```

---

### Scenario S18: Per-symbol strategy assignment
**Priority:** Could
**Slice:** 3

**Gherkin:**
  Given two strategies mapped to symbol subsets
  When  the portfolio runtime starts
  Then  each symbol is evaluated by its assigned strategy
  And   portfolio risk still spans the whole book

> Out of scope for this spec's implementation; documented to confirm the
> Slice 1 interface (a strategy-to-symbol map) does not preclude it.

---

## Coverage matrix (Musts → safety rules from AGENTS.md)

| AGENTS.md trading safety rule | Covered by |
|-------------------------------|------------|
| Dry-run default               | S1 (mode param defaults dry_run)        |
| Live requires explicit ack    | S1 + existing `check_live_mode`         |
| Idempotency (cloid/signal)    | S5                                       |
| Persist before/after effects  | S7 (Trade opened/closed around fills)   |
| Reconcile on startup          | S6                                       |
| Reduce-only exits             | S7, S11 (exit bypass is reduce-only)    |
| Risk gates before every order | S3, S4 (portfolio) + existing per-symbol|
| Kill switch first-class       | S8                                       |
| Closed-bar execution          | inherited — demux is on closed candles  |
