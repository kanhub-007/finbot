# Scenarios — Cross-Asset Strategy Support

## Scenario: Single cross-asset informative (Must, Slice 1)

**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a strategy YAML with `timeframes.informative` containing `{alias: btc_1h, interval: 1h, symbol: BTC}`
  And the primary symbol is `PURR`
  When the bot starts
  Then Finbot opens a primary websocket for `PURR` at the primary interval
  And opens an informative websocket for `BTC` at `1h`
  And warmup bars are loaded from `BTC/1h` Hyperliquid REST
  And each `BTC` closed candle is routed to `process_informative_candle(alias="btc_1h", bar)`
  And the enricher sees the bar under alias `btc_1h`

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| informative.symbol | string | "BTC" | Optional; defaults to primary symbol |
| informative.alias | string | "btc_1h" | Required, unique per entry |
| informative.interval | string | "1h" | Required |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| `StrategyTimeframes.informative_aliases["btc_1h"]` == `"1h"` | Inspect parsed timeframes |
| `StrategyTimeframes.informative_symbols["btc_1h"]` == `"BTC"` | Inspect parsed timeframes |
| Bot loop subscribes informative to `("BTC", "1h")` | Verify `subscribe_candles` called with `symbol="BTC"` |
| Warmup bars loaded from Hyperliquid for `BTC/1h` | Check log output |
| `process_informative_candle("btc_1h", bar)` called with BTC bar | Integration test |

**Verify (Classical school, black-box):**
```python
# Parse a cross-asset strategy definition
from finbot.core.domain.services.strategy_timeframe_parser import parse_timeframes
loader = YamlStrategyDefinitionLoader()
definition = loader.load_from_string("""
strategy:
  kind: json_rule_based
  timeframes:
    primary: 30m
    informative:
      - alias: btc_1h
        interval: 1h
        symbol: BTC
""")
tf = parse_timeframes(definition)
assert tf.is_mtf
assert tf.informative_aliases == {"btc_1h": "1h"}
assert tf.informative_symbols == {"btc_1h": "BTC"}
```

**Also test:**
- Informative without `symbol` → defaults to primary symbol (backward compatible)
- Two cross-asset informatives with different symbols → both symbols subscribed
- Same symbol, different interval → works (e.g., `BTC/1h` + `BTC/4h`)
- Unknown symbol → warmup load fails gracefully; runtime warms from live candles

---

## Scenario: Backward compatibility — no symbol means primary (Must, Slice 1)

**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a strategy YAML declaring `timeframes.informative: [{alias: h1, interval: 1h}]`
  (no `symbol` field)
  When the bot starts
  Then the informative websocket subscribes to the **primary symbol** (same behavior as before)

**Verify:**
```python
definition = loader.load_from_string("""
strategy:
  kind: json_rule_based
  timeframes:
    primary: 30m
    informative:
      - alias: h1
        interval: 1h
""")
tf = parse_timeframes(definition)
assert tf.informative_symbols == {"h1": None}  # None means "use primary"
```

---

## Scenario: Mixed cross-asset + same-symbol informatives (Should, Slice 1)

**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given a strategy with three informatives: `{alias: h1, interval: 1h}` (same symbol),
  `{alias: btc_1h, interval: 1h, symbol: BTC}`, `{alias: eth_4h, interval: 4h, symbol: ETH}`
  And primary symbol is `PURR` at `30m`
  When the bot starts
  Then 4 total market-data websockets are opened: PURR/30m, PURR/1h, BTC/1h, ETH/4h
  And each feeds the correct alias into the enricher pipeline

**Verify:**
```python
tf = parse_timeframes(definition)
assert tf.informative_aliases == {"h1": "1h", "btc_1h": "1h", "eth_4h": "4h"}
assert tf.informative_symbols == {"h1": None, "btc_1h": "BTC", "eth_4h": "ETH"}
```

**Also test:**
- Unique stream count matches unique (symbol, interval) pairs
- Duplicate (symbol, interval) with different aliases → only one websocket opened, both aliases receive it
