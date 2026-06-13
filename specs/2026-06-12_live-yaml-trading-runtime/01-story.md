# Live YAML Trading Runtime

## User Story

As a Finbot operator, I want to run trading strategies defined in YAML against live Hyperliquid market data, so that the same strategies I validate and replay can be dry-run, testnet-traded, and eventually live-traded safely.

## Context

Finbot already has most required building blocks: YAML parsing, validation, strategy evaluation, indicator math, warmup windows, Hyperliquid market data, order planning, risk gates, persistence, order lifecycle tracking, retries, security, and live-mode guards. However, `finbot run` currently performs startup checks and exits. The components are not yet assembled into a continuous live trading runtime.

The next work should turn Finbot into a real runtime while preserving the safety-first rollout: live-data dry-run first, then testnet execution, then controlled live trading. The runtime must support YAML strategies, starting with `amt_dip_buyer_final.yaml` and `amt_v2_vol_filter.yaml`, and reject unsupported YAML features before subscribing to live data or submitting orders.

The runtime must keep Clean Architecture boundaries. Application use cases orchestrate domain interfaces. Infrastructure adapters wrap Hyperliquid SDK, SQLite, YAML loading, and indicator engines. Startup composes the object graph. Domain entities remain pure and independent of SDKs, databases, and frameworks.

## Non-Goals

Things explicitly not being built in this iteration:

- Building a full backtester with fees, slippage, funding, liquidation modelling, or portfolio analytics.
- Supporting arbitrary unsupported Finbar YAML features silently.
- Managing deposits, withdrawals, bridging, transfers, or vault administration.
- Running live mode without explicit `FINBOT_LIVE_TRADING_ACK=true`.
- Running strategy evaluation on websocket callback threads.
- Placing live mainnet orders before dry-run and testnet evidence exists.
- Optimizing for high-frequency trading or sub-second execution.
