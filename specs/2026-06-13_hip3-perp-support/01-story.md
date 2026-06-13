# HIP-3 Perp Support

## User Story
As a trader, I want to trade HIP-3 vault perpetuals (e.g. `xyz:AAPL`, `flx:TSLA`) on Hyperliquid through Finbot, so that I can run Finbar-designed strategies on stock-like instruments alongside crypto perps.

## Context
Hyperliquid supports two kinds of perpetual futures:
- **Standard perps**: plain ticker names like `BTC`, `ETH`, `SOL`. Listed in `info.meta().universe`. Candles via `info.candles_snapshot()`. Websocket via normal candle subscription.
- **HIP-3 vault perps**: `dex:COIN` format like `flx:TSLA`, `xyz:AAPL`, `km:AAPL`. Created by HIP-3 vault providers (DEXes). Listed via `info.perp_dexs()` not `meta().universe`. Candles via `info.post('/info', {'type': 'candleSnapshot', 'req': {'coin': 'dex:COIN', ...}})` — a custom POST, not the standard `candles_snapshot()` method.

Currently Finbot only handles standard perps. The symbol `xyz:AAPL` would fail at multiple points: metadata lookup uses `meta().universe` which doesn't contain it, candle fetching uses `candles_snapshot()` which doesn't support it, and websocket subscription might use the wrong format.

The core pipeline (enrichment, validation, evaluation, risk gates, ordering) is ticker-agnostic and doesn't need changes. Only the infrastructure adapters that touch the Hyperliquid API need to support the `dex:COIN` format.

There are 8 active DEX providers: `xyz`, `flx`, `vntl`, `hyna`, `km`, `abcd`, `cash`, `para`. Each offers a different set of underlying tickers. AAPL is available on `xyz` and `km`; TSLA and NVDA on `flx`.

## Non-Goals
- Spot trading (HIP-3 spot tokens like the spot market AAPL)
- Multi-DEX arbitrage
- Automatic DEX discovery at every API call (cached is fine)
- Changing the strategy evaluation pipeline
