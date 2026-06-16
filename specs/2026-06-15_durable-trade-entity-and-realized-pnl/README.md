# Durable Trade Entity & Realized PnL

**Status:** Draft.
**Created:** 2026-06-15
**Scope:** Tier 1 hardening of the single-symbol runtime. No multi-ticker.

## One-line summary

Give Finbot a **durable per-position `Trade` entity** so that fills are
aggregated into a position lifecycle (open → close), **realized PnL** is
tracked, and the currently-broken `DailyLossGate` actually functions.

## Why

Two confirmed gaps in the current single-symbol runtime:

1. **`DailyLossGate` is configured but never blocks.** It is wired with
   `max_daily_loss_usd=25` (`service_factory.py`), but
   `live_trading_runtime.py` hardcodes the context value
   `"daily_loss_usd": Decimal("0")` with the comment *"daily_loss_usd is 0
   until realized-PnL tracking lands."* The gate reads zero forever. This is
   advertised live safety that silently does nothing.
2. **No durable position concept.** Fills are recorded as standalone
   `FillRecord` rows and advance `OrderLifecycle`, but nothing aggregates
   them into "this position opened at X, closed at Y, +$Z." There is no
   realized PnL, no trade history, no position that survives a restart as a
   first-class object.

## What this spec does NOT do

- **No multi-ticker.** One strategy, one ticker, one instance. (See the
  shelved `2026-06-15_multi-ticker-portfolio-runtime` spec.)
- **No trailing stops.** Not supported by current strategies. (Deferred; the
  `Trade` entity here would enable them later — `max_favorable_price` is
  intentionally omitted to keep scope tight.)
- **No portfolio risk.** No `max_open_positions`, no cross-symbol budget.
- **No unrealized-PnL mark-to-market.** The daily-loss gate uses **realized**
  loss only (deterministic, no live-price dependency at gate-check time).

## Documents

| File | Contents |
|------|----------|
| `01-story.md` | User story, context, 7 decisions, non-goals |
| `02-scenarios.md` | 12 scenarios (MoSCoW) with Gherkin, I/O, Verify blocks |
| `03-domain.md` | `Trade` entity, `TradeLifecycle`, `TradeLedger`, `reconstruct_open`, dry-run synthesis, repo + interface changes |
| `04-implementation.md` | Step-by-step build order (13 steps), sliced |
| `05-architecture.md` | 8 ADRs incl. dry-run fill synthesis (ADR-8) |
| `REVIEW.md` | Self-review findings — all resolved
