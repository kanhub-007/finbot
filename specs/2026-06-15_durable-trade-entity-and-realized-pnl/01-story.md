# Durable Trade Entity & Realized PnL

## User Story

**As a** strategy operator running a live or testnet bot,
**I want** each position I open to be recorded as a durable `Trade` with its
entry, exit, fees, and realized profit/loss,
**so that** (a) the daily-loss kill switch actually protects me — today it is
wired but never fires — and (b) I can see my closed-trade P&L history and
trust that losses are accounted for.

## Context

Finbot enforces risk through a chain of `RiskGate` instances. One of them,
`DailyLossGate`, is configured with `max_daily_loss_usd` (default 25) and is
wired into every live/testnet/dry-run runtime in `service_factory.py`. Its
job: stop the bot opening new entries once cumulative daily loss exceeds the
cap.

But the gate reads its input from the risk context, and
`LiveTradingRuntimeUseCase._build_risk_context()` hardcodes:

```python
"daily_loss_usd": Decimal("0"),
```

with the inline comment: *"daily_loss_usd is 0 until realized-PnL tracking
lands."* So the gate compares `0 >= 25` → always passes. The protection is
**inert**. This is the most important finding from the freqtrade study: a
safety control that exists in config and code but delivers no protection.

The root cause is structural: Finbot has no concept of a **closed position
with a realized result**. `FillRecord` captures individual fills;
`OrderLifecycle` tracks an order's state; `PositionSnapshot` is a transient
exchange read with `unrealized_pnl`. Nothing says "this position opened at
$50,000, closed at $49,000, lost $100." Without that, there is nothing to
sum into a daily loss.

Freqtrade's `Trade` entity solves exactly this: it persists each position's
lifecycle (entry, exit, fees, realized PnL) and the bot's daily-loss logic
reads from it. This spec adopts the **concept** (a durable Trade entity +
realized PnL) without adopting freqtrade's 2,161-line structure — Finbot's
`Trade` is a pure frozen dataclass; all transition logic lives in pure
functions and a small ledger service, following the one-class-per-file and
Clean Architecture rules.

## Decisions

### Decision 1 — New `Trade` entity, distinct from `PositionSnapshot`

`Trade` is the **durable domain record** of one position's lifecycle
(open → close), persisted to SQLite. `PositionSnapshot` remains the
**transient exchange read** (re-fetched each candle). They are reconciled at
startup. Naming avoids the `Position`/`PositionSnapshot` collision. (ADR-1.)

### Decision 2 — Realized loss only (no mark-to-market) for the daily gate

The daily-loss gate uses **realized** loss from closed trades in the current
UTC day only. We deliberately do **not** include unrealized PnL:

- Realized PnL is deterministic and reproducible — no live-price fetch at
  gate-check time, no latency, no price-source dependency.
- It matches what "realized PnL tracking" actually delivers.
- Unrealized mark-to-market is a future enhancement (Should, later slice)
  that needs a defined price source and cadence.

The gate's docstring/comment currently says "realized + unrealized"; it is
updated to "realized" to reflect actual behavior. (ADR-2.)

### Decision 3 — UTC calendar day is the loss window

"Daily" = the current UTC calendar day (resets at 00:00 UTC). Matches the
"use UTC timestamps" convention and is the simplest correct definition.
freqtrade uses trailing windows; we do not need that complexity. (ADR-3.)

### Decision 4 — Fill classification by netting against the open Trade

A fill is classified as an **entry** or **exit** by netting it against the
open Trade for that symbol:

- No open Trade → the fill **opens** a new Trade. Side = LONG if buy, SHORT
  if sell.
- Open Trade exists and fill is in the **opposing** direction (reduces the
  position) → the fill is an **exit** (reduce-only is already enforced by
  `ReduceOnlyGate`, so exits never overshoot for strategy-generated orders).
- Open Trade exists and fill is in the **same** direction → accumulates into
  the entry (avg entry price). Rare for the current single-position model,
  but handled correctly.

This is self-contained in the fill handler and needs no access to the
original `OrderIntent`. (ADR-4.)

### Decision 5 — Trade persistence extends `BotStateRepository`

Trade methods are added to the existing `BotStateRepository` interface (and
both the in-memory and SQLite implementations), matching how
`OrderLifecycle` methods were added. We accept the interface growing rather
than introducing a second `TradeRepository` — consistency with the
established house pattern, and a future split remains possible if it grows
further. (ADR-5.)

### Decision 6 — Trade open/close is atomic with the fill

The Trade ledger update happens **inside the same repository transaction**
as the `FillRecord` write and `OrderLifecycle` advance (the transaction
already exists in `AccountEventHandler._handle_fill`). A crash between them
cannot double-count a fill's size. (ADR-6.)

### Decision 7 — Dry-run synthesizes fills so the ledger tracks positions

In dry-run there is no account stream and the `DryRunExchangeGateway`
emits no fill, so without intervention no Trade would ever open and the
daily-loss gate would never fire there — breaking dry-run/live parity
(AGENTS.md) in the exact mode operators use to validate. The runtime
therefore **synthesizes a fill** on the dry-run submission path and feeds it
to the same `TradeLedger.apply_fill` that live/testnet use. Live/testnet do
**not** synthesize — real fills arrive via the account stream. (ADR-8.)

## Non-Goals

- Multi-ticker / portfolio risk (shelved spec).
- Trailing stops / MFE-MAE tracking (`max_favorable_price` etc.) — not
  supported by strategies; deferred. The entity is designed so they can be
  added later without a schema break (a nullable column + migration).
- Unrealized PnL / mark-to-market in the daily gate.
- Position flips (netting past zero) — reduce-only exits are enforced, so
  strategy signals cannot flip. Manual flips on the exchange are flagged by
  reconciliation, not auto-modeled.
- Fee model changes — `FillRecord.fee` is used as-is; net PnL subtracts
  total fees.
- A separate `TradeRepository` interface (see Decision 5).
- Amending past `OrderIntent` to carry a back-reference (see Decision 4 —
  not needed for fill classification).

## Relationship to existing work

- **`DailyLossGate`** — unchanged code; it starts working once the context
  value is real instead of zero. No gate rewrite.
- **`AccountEventHandler`** — gains a `TradeLedger` dependency; the fill
  handler calls it inside the existing transaction.
- **`PositionSnapshot`** — unchanged (transient exchange read).
- **`BotStateRepository` / SQLite migrator** — extended (new `trades` table,
  migration v3).
- **Shelved multi-ticker spec** — its "Phase 0" *is* this spec. If/when
  multi-ticker is revived, the `Trade` entity and realized PnL are already
  in place and reusable.
