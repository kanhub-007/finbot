# Architecture Decisions — Durable Trade Entity & Realized PnL

---

# ADR-1: New `Trade` entity, distinct from `PositionSnapshot`

**Context:**
Finbot tracks orders (`OrderIntent`, `OrderLifecycle`), fills (`FillRecord`),
and a transient exchange position (`PositionSnapshot`, re-fetched each candle
with `unrealized_pnl`). It has no durable object representing "a position I
opened, held, and closed, with a realized result." Without that, there is
nothing to aggregate into a daily loss — which is why `DailyLossGate` is fed
zeroes.

**Decision:**
Introduce a `Trade` domain entity: a frozen dataclass persisted to a new
SQLite `trades` table, recording one position's lifecycle (open → close)
including volume-weighted entry, exit, fees, and realized PnL. It is
**distinct from** `PositionSnapshot` (the live exchange read) — the two are
reconciled at startup, never conflated.

**Naming:** `Trade`, not `Position`, to avoid collision with the existing
`PositionSnapshot` / `PositionDirection`. A trade = the durable lifecycle
record of one position. This matches freqtrade's concept without importing
its 2,161-line anemic-but-fat model — finbot's `Trade` is a pure dataclass
and all logic lives in `TradeLifecycle` + `TradeLedger`.

**Consequences:**
- `DailyLossGate` finally has a real input (sum of closed-trade losses).
- Trade history and realized PnL become first-class queryable data.
- One new table + migration (additive, no existing column changes).
- `Trade` is additive: nothing existing depends on it yet except the gate
  context value, so the blast radius is small.

---

# ADR-2: Daily-loss gate uses realized loss only (no mark-to-market)

**Context:**
The gate's existing comment says "realized + unrealized loss." Unrealized
PnL requires a live mark price at gate-check time — a price source, latency,
and a defined cadence. Realized PnL (from closed trades) is deterministic,
reproducible, and is exactly what "realized PnL tracking" delivers.

**Decision:**
The daily-loss gate uses **realized** loss from closed trades in the current
UTC day only. The gate's docstring is corrected to "realized." Unrealized
mark-to-market is a future enhancement with its own ADR (price source,
cadence, whether it gates entries only).

**Consequences:**
- The gate is testable without a live price feed (deterministic).
- Protection kicks in after losses are *realized* — an open losing position
  does not trip the gate until it closes. This is the honest, reproducible
  semantics; if unrealized protection is needed, it is added explicitly later.
- Operators must understand "daily loss" means realized-to-date today, not
  current drawdown. Documented in the gate docstring + README.

---

# ADR-3: UTC calendar day is the loss window

**Context:**
"Daily" needs a precise boundary. Options: trailing 24h rolling window
(freqtrade-style), or calendar day. The rolling window needs a timestamp
scan every check; the calendar day is a simple `DATE(closed_at) = today`
predicate with an index.

**Decision:**
Daily = current UTC calendar day, resetting at 00:00 UTC. Matches the
"use UTC timestamps" convention in AGENTS.md and is the simplest correct
definition.

**Consequences:**
- The `realized_loss_on(day)` query is a single indexed predicate.
- A loss at 23:59 UTC and one at 00:01 UTC fall in different days (tested in
  S6).
- No sliding-window complexity or clock-skew sensitivity beyond UTC.

---

# ADR-4: Fill classification by netting (no OrderIntent access needed)

**Context:**
When a fill arrives, the ledger must decide: does it open a new Trade,
accumulate into an open one, or close one? The cleanest signal is the
`reduce_only` flag on the original `OrderIntent` — but `AccountEventHandler`
only has the fill event + `OrderLifecycle`, not the intent. Linking fill →
intent requires chasing `order_id` (buried in `response_json`) or `cloid`,
which adds lookup machinery.

**Decision:**
Classify by **netting the fill against the open Trade** for that symbol:
no open Trade → opens; open Trade + opposing direction → exits; open Trade +
same direction → accumulates. This is self-contained in the fill handler and
needs no intent lookup. It is also the standard position-accounting approach.

**Consequences:**
- `AccountEventHandler` needs only the `TradeLedger`, not intent access.
- `entry_signal_key` / `strategy_hash` on the Trade are **best-effort**
  (`strategy_hash` is derivable from `bot_run_id`; `entry_signal_key` needs
  the cloid→intent lookup and may be empty initially). They are audit fields,
  not functional — the PnL/daily-loss logic does not depend on them.
- Reduce-only is already enforced upstream by `ReduceOnlyGate`, so strategy
  exits never overshoot. A manual flip on the exchange would net past zero;
  reconciliation flags it rather than modeling a flip (Non-Goal).

---

# ADR-5: Extend `BotStateRepository`, do not split a `TradeRepository`

**Context:**
Adding 6 Trade methods to `BotStateRepository` grows an already-large
interface (~30 methods). SOLID's interface-segregation principle suggests a
separate `TradeRepository`. But the established house pattern is one state
repo implemented by both the in-memory and SQLite repos; `OrderLifecycle`
methods were added the same way. Splitting now means both repos grow a
second interface and wiring doubles.

**Decision:**
Extend `BotStateRepository` with the Trade methods, matching the
`OrderLifecycle` precedent. Keep a single repo. A split remains a clean
future refactor if the interface keeps growing — it is not precluded by this
design (Trade methods are cohesive and could be extracted later).

**Consequences:**
- Consistency with existing code; one repo to wire.
- Both impls (in-memory, SQLite) gain the methods.
- The interface is large but cohesive (all "bot state"). If it crosses a
  pain threshold, extract `TradeRepository` + `OrderRepository` together.

---

# ADR-6: Trade open/close is atomic with the fill (shared transaction)

**Context:**
`AccountEventHandler._handle_fill` already wraps the `FillRecord` write and
`OrderLifecycle` advance in a single repository transaction (to avoid
double-counting a fill's size on retry, per an existing comment). The Trade
update is a third effect in the same critical section.

**Decision:**
`TradeLedger.apply_fill` does **not** open its own transaction. It runs
inside the caller's existing transaction in `_handle_fill`. The three
effects (fill record, lifecycle advance, Trade update) commit atomically or
not at all.

**Consequences:**
- A crash between recording the fill and updating the Trade cannot leave the
  book inconsistent (no double-counted size, no orphaned open Trade).
- `TradeLedger` is simpler (no transaction management) and stays a pure
  domain collaborator.
- The in-memory repo (no `transaction()`) calls `apply_fill` directly —
  already the existing fallback path.

---

# ADR-7: Borrow freqtrade's Trade *concept*, not its structure

**Context:**
freqtrade's `Trade` model (2,161 lines) is the inspiration: a durable
per-position record enabling realized PnL and loss-based protections. But
its structure mixes data, ORM mapping, lifecycle logic, fee detection, and
liquidation math in one class — exactly the "God Class" finbot's constitution
bans.

**Decision:**
Adopt the **concept** (durable Trade + realized PnL feeding a loss gate) and
re-express it in finbot's Clean Architecture: a pure frozen `Trade`
dataclass, a stateless `TradeLifecycle` function module, a thin `TradeLedger`
service, inline ORM mapping in the existing repo, and Classical-school
black-box tests.

**Consequences:**
- Finbot gains freqtrade's position-accounting capability without its
  maintainability debt.
- Each piece is independently testable (TradeLifecycle has zero
  dependencies; TradeLedger takes only a repo).
- The mapping from freqtrade idea → finbot component is explicit and reviewed.

---

# ADR-8: Dry-run synthesizes fills so the ledger tracks positions

**Context:**
The daily-loss gate only works if Trades open/close from fills. In live and
testnet, fills arrive via the account websocket stream and are handled by
`AccountEventHandler`. But in dry-run:
- `DryRunExchangeGateway.submit_order()` returns `{"status":"dry_run"}` and
  emits **no fill event**.
- dry-run builds the bot loop with `account=False`, so there is no account
  stream and `AccountEventHandler` is never called.

So without intervention, **no Trade ever opens in dry-run**, the daily-loss
gate never fires there, and dry-run/live parity (AGENTS.md) is broken in
exactly the mode operators use for validation.

**Decision:**
The runtime synthesizes a fill on the dry-run submission path and feeds it
directly to `TradeLedger.apply_fill`. The synthetic fill uses the latest
bar's close as price (already in the warmup window) and derives `fill_id`
from the intent id (idempotent across replays). Live/testnet do **not**
synthesize — real fills arrive via the account stream.

**Why the runtime owns this, not the gateway:** the runtime already owns the
warmup bar (the price source) and the ledger. Pushing synthesis into the
gateway would couple it to the event queue. Keeping it in the runtime's
`_dispatch_submission` keeps the dry-run/live convergence in one place and
leaves the gateway a pure no-op adapter.

**Consequences:**
- Dry-run and live converge on the same `TradeLedger.apply_fill` path — the
  daily-loss gate protects dry-run identically.
- The synthetic fill is deterministic and idempotent (intent-derived id), so
  replays don't double-count.
- One new helper (`_synthesize_fill`) and one call site change in
  `_dispatch_submission`.
