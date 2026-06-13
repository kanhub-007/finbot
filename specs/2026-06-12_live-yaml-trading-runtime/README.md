# Live YAML Trading Runtime

**Date:** 2026-06-12  
**Cynefin classification:** Complicated — the desired behaviour is knowable and testable, but requires careful integration across strategy parsing, market data, indicator enrichment, risk gates, persistence, exchange execution, and live-mode safety.

## Root Cause

Finbot has most trading components implemented and tested, but `finbot run` does not yet operate as a live trading runtime. It validates startup state and exits. The user needs Finbot to run YAML-defined strategies continuously against Hyperliquid candle data, first in live-data dry-run, then testnet, then tightly gated live mode.

## Summary

Build the next execution phases so Finbot can:

1. Load a supported YAML strategy.
2. Warm up historical candles.
3. Subscribe to Hyperliquid closed candles.
4. Enrich candles with required indicators.
5. Validate enriched candle quality before decisions: required columns present, latest values finite, no warmup gaps, no partial candles.
6. Evaluate entry/exit rules.
7. Plan orders through risk gates.
8. Persist signals, risk decisions, intents, responses, fills, and lifecycle state.
9. Simulate dry-run orders without secrets.
10. Submit testnet orders with idempotent `cloid`.
11. Unlock live trading only behind explicit, audited safety gates.

## Proposed Phase Map

| Phase | Name | Outcome |
|-------|------|---------|
| 17 | Live execution pipeline integration | `finbot run` blocks, subscribes, processes closed candle events |
| 18 | YAML strategy runtime wiring | Real `RuleBasedStrategyEvaluator` is used for supported YAML strategies |
| 19 | Live indicator enrichment + validation gate | Live candles are warmed up, enriched, quality-checked, then allowed into strategy evaluation |
| 20 | Live-data dry-run order simulation | Accepted intents are persisted and simulated, never submitted |
| 21 | Testnet execution pipeline | Accepted intents are normalized and submitted to Hyperliquid testnet |
| 22 | Account websocket updates | Order/fill updates drive order lifecycle state |
| 23 | Controlled live rollout | Live mode runs only after every safety gate passes |

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Create a new `LiveTradingRuntimeUseCase` instead of bloating `RunBotUseCase` | Keeps orchestration focused and testable |
| Keep SDK callbacks enqueue-only | Prevents strategy/exchange logic from running on websocket threads |
| Dry-run and testnet share the same pipeline until submission boundary | Prevents dry-run/testnet behaviour drift |
| YAML strategies must pass compatibility before websocket subscription | Fail fast before connecting or placing orders |
| Use fakes for tests | Classical-school tests should verify outcomes, not interactions |
| Live requires durable SQLite persistence | Duplicate prevention and reconciliation must survive restart |

## Files

- `01-story.md` — story, context, non-goals
- `02-scenarios.md` — behaviour scenarios with Gherkin, I/O tables, and Verify blocks
- `03-domain.md` — entities, value objects, events, interfaces
- `04-implementation.md` — implementation steps for a junior developer
- `05-architecture.md` — architecture decisions
