# Cross-Asset Strategy Support

## User Story
As a strategy author, I want to use OHLCV data from a different symbol (e.g., BTC)
to inform trading decisions on my primary symbol (e.g., an altcoin), so that
strategies can incorporate market-wide context (BTC dominance, sector rotation,
correlation signals).

## Context

Finbot currently supports **multi-timeframe (MTF)** strategies where informative
timeframes deliver candles for the **same symbol** at different intervals. For
example, a strategy on `ETH` can read `ETH-1h` and `ETH-4h` bars alongside the
primary `ETH-30m` bars.

Cross-asset extends this: an informative entry in the strategy YAML's
`timeframes` block can declare an optional `symbol` field. When present, Finbot
opens a separate websocket for that `(symbol, interval)` pair and feeds the bars
into the same per-alias enricher pipeline. The enricher and strategy evaluator
are already symbol-agnostic — they operate on bar dicts keyed by alias. The
change is entirely in the websocket wiring and warmup-bar loading.

Hyperliquid's websocket connection limit (10+) comfortably supports 3–5
concurrent streams for a typical cross-asset strategy (primary + 1–2 cross-asset
informatives + account stream).

## Non-Goals
- **Cross-exchange data** — all symbols must be on Hyperliquid.
- **Cross-asset feature formulas** — the `features` block of a strategy already
  supports arbitrary column references; no new DSL syntax is added here.
- **Cross-asset warmup from CSV** — warmup bars are loaded from Hyperliquid REST.
- **Dynamic symbol resolution** — symbols are static, defined in the YAML.
