# Domain Model — HIP-3 Perp Support

Mostly reuses existing entities. One new value object for symbol parsing.

## Value Objects

| Value Object | Fields | Used where |
|-------------|--------|------------|
| `ParsedSymbol` | `raw: str`, `is_hip3: bool`, `dex: str`, `coin: str`, `api_symbol: str` | Symbol parsing before any API call; used by market data, metadata, and exchange adapters |

## Interfaces (updated)

| Interface | Change | Reason |
|-----------|--------|--------|
| `MarketMetadataProvider.get_metadata(symbol)` | Already takes `str` | `xyz:AAPL` passes as-is, no signature change |
| `BarSource` / `BarLoader` | Existing `load_bars(symbol, interval, ...)` | Already takes `str` symbol, no change |
| `MarketDataStream.subscribe_candles(symbol, ...)` | Already takes `str` | HIP-3 symbol passes as-is |
| `ExchangeGateway` | Already takes `symbol: str` | No change needed |

## New Domain Service

| Service | Responsibility |
|---------|---------------|
| `SymbolParser` (`core/domain/services/symbol_parser.py`) | Pure function: detect `:` in symbol, split into dex and coin, validate format. No I/O. |

## Entity vs ORM separation

No new entities. All existing entities (SignalDecision, OrderIntent, PositionSnapshot) already use `str` for symbol and don't care about format.

## Invariants

- Standard perps must continue to work unchanged — no regression in any existing test
- HIP-3 symbol format is `dex:COIN` with lowercase dex and uppercase coin
- An empty dex or coin in a `:containing` symbol is invalid
- DEX provider list is cached for 5 minutes (aligned with existing Finbar convention)
