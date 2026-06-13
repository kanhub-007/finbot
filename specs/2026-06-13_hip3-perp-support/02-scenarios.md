# Scenarios — HIP-3 Perp Support

All scenarios use Classical school, black-box testing with fakes.

---

### Scenario: Standard perps continue to work unchanged
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a standard perp symbol like "BTC"
  When the runtime starts, loads metadata, fetches candles, and subscribes
  Then all paths work exactly as before without any regressions

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| symbol | str | `BTC` | No `:` in name |
| interval | str | `1h` | Standard HL interval |

**Expected output:**
| Assertion | How to verify |
|-----------|---------------|
| existing tests all pass | pytest tests/ -q |
| replay with BTC bars works | CLI replay output matches |

**Verify:**
```python
# Existing tests must not break
pytest tests/ -q
```

**Also test:**
- ETH, SOL, and other standard perps all work
- No `:` symbol detection needed for standard path

---

### Scenario: HIP-3 symbol is detected and routed to HIP-3 API path
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a HIP-3 symbol like "xyz:AAPL" or "flx:TSLA"
  When the runtime needs market metadata, candles, or a websocket subscription
  Then it detects the `:` separator and routes to the HIP-3 API path instead of the standard perp path

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| symbol | str | `xyz:AAPL` | Contains `:` separator, lowercase dex, uppercase coin |
| dex | str | `xyz` | Part before `:` |
| coin | str | `AAPL` | Part after `:` |

**Expected output:**
| Assertion | How to verify |
|-----------|---------------|
| symbol is detected as HIP-3 | `is_hip3_symbol("xyz:AAPL")` returns True |
| symbol is detected as standard | `is_hip3_symbol("BTC")` returns False |
| metadata is fetched via HIP-3 path | Fake metadata provider uses perp_dexs endpoint |
| candles are fetched via POST | Fake bar source uses candleSnapshot POST |

**Verify:**
```python
from finbot.core.domain.services.symbol_parser import parse_symbol

result = parse_symbol("xyz:AAPL")
assert result.is_hip3 is True
assert result.dex == "xyz"
assert result.coin == "AAPL"
assert result.api_symbol == "xyz:AAPL"

std = parse_symbol("BTC")
assert std.is_hip3 is False
assert std.api_symbol == "BTC"
```

**Also test:**
- `flx:TSLA` → dex=flx, coin=TSLA
- `BTC` → is_hip3=False
- `ETH` → is_hip3=False
- Empty symbol → raises ValueError
- Symbol with only `:` → raises ValueError

---

### Scenario: HIP-3 metadata is discovered from perp_dexs endpoint
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a HIP-3 symbol
  When the runtime starts and needs market metadata (szDecimals, price tick, etc.)
  Then it queries `info.perp_dexs()` for the DEX list and fetches token-level metadata

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| dex | str | `flx` | Must be a known DEX provider |
| coin | str | `TSLA` | Must be a token offered by that DEX |
| api_url | str | `https://api.hyperliquid.xyz` | Mainnet or testnet |

**Expected output:**
| Assertion | How to verify |
|-----------|---------------|
| DEX list is cached | Second call doesn't hit API |
| Token metadata has szDecimals | Inspect returned MarketMetadata |
| Unknown DEX returns None | Inspect metadata result |
| Unknown token returns None | Inspect metadata result |

**Verify:**
```python
fake_info = FakeInfoClient(perp_dexs=[{"name": "flx"}])
provider = HyperliquidMetadataProvider(info=fake_info)

meta = provider.get_metadata("flx:TSLA")
assert meta is not None
assert meta.sz_decimals > 0
```

**Also test:**
- DEX list cache expires after 5 minutes
- `xyz:AAPL` returns valid metadata
- `unknown:COIN` returns None

---

### Scenario: HIP-3 candles are fetched via candleSnapshot POST
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a HIP-3 symbol and a time range
  When the warmup or bar source needs historical candles
  Then it calls `info.post('/info', {'type': 'candleSnapshot', 'req': {'coin': 'dex:COIN', ...}})` instead of `info.candles_snapshot()`

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| symbol | str | `xyz:AAPL` | HIP-3 format |
| interval | str | `1h` | Standard HL interval |
| start_ms | int | 1749000000000 | Unix ms |
| end_ms | int | 1750000000000 | Unix ms |

**Expected output:**
| Assertion | How to verify |
|-----------|---------------|
| candles returned in standard OHLCV format | List of dicts with o, h, l, c, v, t |
| timestamp normalized to seconds | t // 1000 |
| empty response handled | Returns empty list, no crash |

**Verify:**
```python
fake_info = FakeInfoClient(hip3_candles=[{"t": 1749000000, "o": "290", ...}])
source = HyperliquidBarSource(info=fake_info)
bars = source.load_bars("xyz:AAPL", "1h", start_ms, end_ms)
assert len(bars) > 0
assert bars[0]["close"] == Decimal("290.38")
```

**Also test:**
- Standard perp still uses `candles_snapshot()` (no regression)
- 500 error from API → empty list, logged warning

---

### Scenario: HIP-3 websocket candle subscription works
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given a HIP-3 symbol
  When the market data stream subscribes to live candles
  Then it uses the `dex:COIN` format in the subscription message

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| symbol | str | `xyz:AAPL` | HIP-3 format |
| interval | str | `1h` | Standard HL interval |

**Expected output:**
| Assertion | How to verify |
|-----------|---------------|
| subscription uses `dex:COIN` coin field | Inspect websocket subscribe message |
| candle messages are parsed correctly | Inspect enriched bar output |

**Also test:**
- Standard perp still subscribes normally

---

### Scenario: HIP-3 orders execute through Exchange gateway
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a HIP-3 symbol order intent
  When the exchange gateway submits the order
  Then it passes `dex:COIN` as the coin/symbol to the SDK

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| symbol | str | `xyz:AAPL` | HIP-3 format |
| side | OrderSide | BUY | Standard |
| size | Decimal | 0.01 | Positive |

**Expected output:**
| Assertion | How to verify |
|-----------|---------------|
| order submitted with correct symbol | Fake exchange records `xyz:AAPL` |
| position query uses correct symbol | Fake exchange returns position for `xyz:AAPL` |

**Verify:**
```python
fake_exchange = FakeExchangeGateway()
gateway = HyperliquidExchangeGateway(exchange=fake_exchange)
gateway.submit_order(OrderIntent(symbol="xyz:AAPL", side=BUY, size=Decimal("0.01"), ...))
assert fake_exchange.last_symbol == "xyz:AAPL"
```

**Also test:**
- Cancel order uses `xyz:AAPL`
- Position query uses `xyz:AAPL`
- Standard perp order still works
