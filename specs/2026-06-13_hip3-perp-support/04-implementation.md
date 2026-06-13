# Implementation Guide — HIP-3 Perp Support

Follow Red → Green → Refactor per scenario. No existing tests should break.

---

## Slice 1 — Core HIP-3 support

### Step 1: Create `SymbolParser` value object
**File:** `finbot/core/domain/services/symbol_parser.py`

Pure domain service. Detects `:` separator, validates format.

```python
@dataclass(frozen=True)
class ParsedSymbol:
    raw: str
    is_hip3: bool
    dex: str = ""
    coin: str = ""
    api_symbol: str = ""

def parse_symbol(raw: str) -> ParsedSymbol:
    if not raw or not raw.strip():
        raise ValueError("symbol must not be empty")
    if ":" not in raw:
        return ParsedSymbol(raw=raw, is_hip3=False, api_symbol=raw)
    parts = raw.split(":")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid HIP-3 symbol format: {raw}")
    dex, coin = parts[0].lower(), parts[1].upper()
    return ParsedSymbol(raw=raw, is_hip3=True, dex=dex, coin=coin, api_symbol=f"{dex}:{coin}")
```

**Verify:**
```bash
pytest tests/test_domain/test_symbol_parser.py -q
```

---

### Step 2: Route candle fetching based on symbol type
**File:** `finbot/infrastructure/adapters/hyperliquid_market_data_stream.py`

In the candle subscription and any historical fetch path, detect HIP-3 symbols and use the `candleSnapshot` POST pattern.

**Verify:**
```bash
pytest tests/test_infrastructure/test_hyperliquid_market_data_stream.py -q
```

---

### Step 3: Route metadata lookup based on symbol type
**File:** `finbot/infrastructure/adapters/hyperliquid_metadata_provider.py`

For HIP-3 symbols, first check `perp_dexs()` list (cached), then fetch token metadata. For standard perps, use existing `meta()` path.

**Verify:**
```bash
pytest tests/test_infrastructure/ -k metadata -q
```

---

### Step 4: Verify exchange gateway passes `dex:COIN` through
**File:** `finbot/infrastructure/adapters/hyperliquid_exchange_gateway.py`

The SDK's `Exchange` class should handle `dex:COIN` symbols natively since it uses `info.post()` internally. Verify with a test that passes `flx:TSLA` through the gateway.

**Verify:**
```bash
pytest tests/test_infrastructure/test_hyperliquid_exchange_gateway.py -q
```

---

### Step 5: HIP-3 bar source for historical warmup
**File:** `finbot/infrastructure/strategy/hyperliquid_bar_source.py` (new)

A `BarSource` implementation that fetches candles from Hyperliquid for both standard and HIP-3 symbols. Routes to `candles_snapshot` for standard, `candleSnapshot` POST for HIP-3.

**Verify:**
```bash
pytest tests/test_infrastructure/ -k bar_source -q
```

---

### Step 6: Full regression
```bash
pytest tests/ -q
ruff check finbot tests
```

All 774 existing tests must pass. New HIP-3 tests must pass.
