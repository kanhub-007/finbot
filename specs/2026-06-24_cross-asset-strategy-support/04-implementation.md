# Implementation Guide — Cross-Asset Strategy Support

## Step 1: Extend `StrategyTimeframes` value object
**File:** `finbot/core/domain/entities/strategy_timeframes.py`
Add `informative_symbols` field and `effective_symbol()` helper.

**Verify:** `python -m pytest tests/test_domain/test_strategy_timeframe_parser.py -v`

## Step 2: Update `StrategyTimeframeParser` to parse `symbol`
**File:** `finbot/core/domain/services/strategy_timeframe_parser.py`
Extract `item.symbol` from each informative entry; store `None` when absent.

**Verify:** New test: parse YAML with and without `symbol` field.

## Step 3: Update `YamlStrategyDefinitionLoader.last_timeframes()`
**File:** `finbot/infrastructure/strategy/yaml_strategy_definition_loader.py`
Ensure the loader passes the `symbol` field through when the package parses
the YAML. (The package's `StrategyTimeframeDeclaration` may already support
an optional `symbol` field — verify and map it.)

**Verify:** `python -m pytest tests/test_infrastructure/test_yaml_strategy_definition_loader.py -v`

## Step 4: Update `BotEventLoop` to accept per-informative symbols
**File:** `finbot/infrastructure/adapters/bot_event_loop.py`
- Add `informative_symbols: list[str | None] | None` to constructor and `start()`
- In `_subscribe_informative()`, use `informative_symbols[i]` (or primary) when subscribing

**Verify:** Unit test that `subscribe_candles(symbol, interval)` is called with the correct symbol per stream.

## Step 5: Update `RuntimeFactory` to wire cross-asset streams + warmup
**File:** `finbot/startup/runtime_factory.py`
- Build one `HyperliquidMarketDataStream` per unique `(symbol, interval)` pair
- Pass `informative_symbols` list to `BotEventLoop` / `LiveTradingRuntimeBuilder`
- Load warmup bars per `(symbol, interval)` pair, not just per interval

**Verify:** `python -m pytest tests/test_startup/test_live_runtime_wiring.py -v`

## Step 6: Integration test
**File:** `tests/test_application/test_cross_asset_integration.py` (new)
- Strategy YAML with cross-asset informative
- Verify warmup bars are loaded from the cross-asset symbol
- Verify the enricher receives bars under the correct alias

**Verify:** `python -m pytest tests/test_application/test_cross_asset_integration.py -v`

## Step 7: Update `RuntimeFactory` to handle duplicate (symbol, interval) pairs
**File:** `finbot/startup/runtime_factory.py`
When two informatives share the same `(symbol, interval)` but different aliases,
open only ONE websocket and route its candles to both aliases. This avoids
wasting a Hyperliquid websocket slot on duplicate subscriptions.

**Verify:** Integration test with two aliases on the same `(symbol, interval)`.
