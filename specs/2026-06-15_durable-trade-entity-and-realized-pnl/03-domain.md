# Domain Model — Durable Trade Entity & Realized PnL

All new types follow one-class-per-file and Clean Architecture. Existing
entities are referenced, not redefined.

## New Entity

### `Trade` — durable per-position record

The portfolio primitive finbot currently lacks. Distinct from the transient
`PositionSnapshot` (exchange read) and the per-event `FillRecord`.

**File:** `finbot/core/domain/entities/trade.py`

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from finbot.core.domain.entities.position_direction import PositionDirection


@dataclass(frozen=True)
class Trade:
    """Durable record of one position's lifecycle (open → close)."""

    position_id: str                          # uuid4
    bot_run_id: str
    symbol: str
    side: PositionDirection                   # LONG or SHORT (never FLAT)
    size: Decimal                             # current open size (base units)
    entry_price: Decimal                      # volume-weighted avg entry
    opened_at: datetime                       # first entry fill time (UTC)
    status: str = "open"                      # "open" | "closed"
    # Realized so far while open; final once closed.
    realized_pnl: Decimal = Decimal("0")
    total_fee: Decimal = Decimal("0")         # accumulated entry+exit fees
    closed_at: datetime | None = None
    close_price: Decimal | None = None
    # Best-effort audit linkage (may be None — see ADR-4):
    strategy_hash: str = ""
    entry_signal_key: str = ""
```

**Field notes:**

- `size` decrements as exits fill; status flips to `"closed"` when size hits 0.
- `realized_pnl` accrues on each exit fill (model (a) from S3) and is final
  at close. Net of fees.
- `entry_price` is the volume-weighted average across entry fills.
- **Deliberately omitted** (to keep scope tight): `max_favorable_price` /
  `max_adverse_price` (trailing stops — not supported by strategies),
  `stop_price` / `target_price` (signal metadata — linkage is indirect; see
  ADR-4). Both are additive nullable columns later if needed.

**Audit-field population (Slice 1 rule):** populate `strategy_hash` from
`self._strategy_hash` (the runtime already holds it — it is the hash of the
loaded strategy file). Leave `entry_signal_key = ""` for Slice 1; populating
it requires an `order_id → intent_id` (via `cloid`) lookup that is out of
scope. Both fields are audit-only — the PnL and daily-loss logic do not
depend on them.

**Persisted:** Yes — new SQLite table `trades` (migration v3).

| Domain entity | ORM model | Mapper |
|---------------|-----------|--------|
| `Trade` (`core/domain/entities/trade.py`) | `TradeOrm` (in-repo, SQLAlchemy-free raw SQL like the other tables) | row↔dataclass mapping inside `sqlite_bot_state_repository.py` (matching existing house style — no separate mapper file for the other entities) |

> The existing repo maps entities inline (e.g. `FillRecord` rows are built
> inside `record_fill`/`get_fills_for_run`). `Trade` follows the same inline
> mapping to stay consistent. A dedicated `trade_mapper.py` is only warranted
> if the mapping grows complex; it does not here.

---

## New Domain Services

### `TradeLifecycle` — pure transition functions

Stateless pure functions that produce new immutable `Trade` instances from
fills. No I/O, no repo. Trivially unit-testable.

**File:** `finbot/core/domain/services/trade_lifecycle.py`

```python
def open_from_fill(fill: FillRecord, position_id: str,
                   strategy_hash: str = "") -> Trade:
    """Create a new open Trade from an entry fill. side from fill.side."""

def apply_entry_fill(trade: Trade, fill: FillRecord) -> Trade:
    """Accumulate an entry fill: size += fill.size, recompute weighted avg
    entry_price, add fee. Returns a new Trade (frozen)."""

def apply_exit_fill(trade: Trade, fill: FillRecord) -> Trade:
    """Apply a reduce fill: size -= fill.size, accrue realized_pnl for the
    closed portion (net of fee), set close_price/closed_at when size == 0.
    Long pnl = (fill.price - entry_price) * filled * sign; short inverted."""

def realized_pnl_for_exit(trade: Trade, exit_price: Decimal,
                          size: Decimal) -> Decimal:
    """PnL for closing `size` units at exit_price, before fees. Pure."""

def sign_for(side: PositionDirection) -> int:
    """+1 for LONG, -1 for SHORT."""
```

**PnL formula (net of fees),** per exit fill (uses `sign_for(side)`):
```
gross   = (exit_price - entry_price) * filled_size * sign_for(side)
net     = gross - fill.fee
realized_pnl (running) += net
total_fee += fill.fee
```

### `TradeLedger` — the accountant (orchestrates open/close)

The domain service that decides, for an incoming fill, whether it opens,
accumulates, or closes a Trade, then persists via the repo **inside the
caller's transaction**. Encapsulates the classification rule (Decision 4)
so `AccountEventHandler` stays a thin dispatcher.

**File:** `finbot/core/domain/services/trade_ledger.py`

```python
class TradeLedger:
    """Aggregates fills into Trade lifecycle records."""

    def __init__(self, repo: BotStateRepository): ...

    def apply_fill(self, fill: FillRecord) -> FillOutcome:
        """Classify + apply a fill to the Trade book.

        - duplicate fill_id -> skipped (idempotent)
        - no open trade      -> opens a new Trade
        - open trade, reduce -> exits (partial or full)
        - open trade, same   -> accumulates entry
        Persists inside the caller's transaction (does NOT open its own).
        """

    def open_trade_for(self, symbol: str) -> Trade | None:
        """Read-only: the current open Trade for a symbol."""

    def realized_loss_on(self, day: date) -> Decimal:
        """Sum of negative realized PnL from trades closed on `day` (UTC).
        Positive results contribute 0 (a loss gate counts losses only).
        Delegates to repo.realized_loss_on(day). The runtime calls THIS
        method (not the repo directly) so the ledger is the single
        read-path for loss data."""

    def reconstruct_open(self, position: PositionSnapshot, *,
                         bot_run_id: str,
                         strategy_hash: str = "") -> Trade:
        """Build an open Trade from an exchange position with no fill history.

        Used at startup reconciliation when the exchange reports an open
        position but the DB has no Trade for it (e.g. crash mid-session).
        - size   = abs(position.size)
        - side   = position.direction (LONG/SHORT; FLAT must not reach here)
        - entry_price = None  (unknown without fill history)
        - opened_at   = datetime.now(UTC)
        - realized_pnl= Decimal("0"), total_fee = Decimal("0")
        Caller persists via repo.open_trade(trade) and records a
        ReconciliationRecord noting entry_price is unknown/best-effort.
        """
```

**`FillOutcome`** (new DTO, `core/domain/dto/fill_outcome.py`):
```python
@dataclass(frozen=True)
class FillOutcome:
    status: str            # "opened" | "accumulated" | "closed" | "partial" | "duplicate"
    position_id: str = ""
    realized_pnl: Decimal | None = None
```

---

## Repository changes (`BotStateRepository`)

Extended (Decision 5), not a new interface. New abstract methods:

**File:** `finbot/core/domain/interfaces/bot_state_repository.py` (modified)

```python
# -- trades ---------------------------------------------------------------
@abstractmethod
def open_trade(self, trade: Trade) -> None: ...
@abstractmethod
def update_trade(self, trade: Trade) -> None: ...
    # used for accumulate / partial-close / full-close (frozen entity -> replace row)
@abstractmethod
def get_open_trade(self, symbol: str) -> Trade | None: ...
@abstractmethod
def list_open_trades(self) -> list[Trade]: ...
@abstractmethod
def list_closed_trades(self, *, bot_run_id: str | None = None) -> list[Trade]: ...
@abstractmethod
def realized_loss_on(self, day: date) -> Decimal: ...
    # SUM(realized_pnl) WHERE status='closed' AND realized_pnl < 0
    #  AND DATE(closed_at)=day
```

**In-memory impl:** `in_memory_bot_state_repository.py` — dict keyed by
`position_id`, plus a list for history.

**SQLite impl:** `sqlite_bot_state_repository.py` — new `trades` table.

---

## SQLite migration (v3)

**File:** `finbot/infrastructure/repositories/sqlite_migrator.py` (modified)

Append a new `(3, "...")` tuple **to the end of the `MIGRATIONS` list**
(after the existing `(2, ...)` entry). Do not edit existing migrations.
`LATEST_VERSION` auto-updates via `max(v for v, _ in MIGRATIONS)`, so it
becomes 3 with no further change.

```sql
(
  3,
  """
  CREATE TABLE IF NOT EXISTS trades (
      position_id      TEXT PRIMARY KEY,
      bot_run_id       TEXT NOT NULL REFERENCES bot_runs(run_id),
      symbol           TEXT NOT NULL,
      side             TEXT NOT NULL,          -- long | short
      size             TEXT NOT NULL,          -- current open size (Decimal)
      entry_price      TEXT NOT NULL,          -- volume-weighted avg
      opened_at        TEXT NOT NULL,          -- ISO UTC
      status           TEXT NOT NULL,          -- open | closed
      realized_pnl     TEXT NOT NULL DEFAULT '0',
      total_fee        TEXT NOT NULL DEFAULT '0',
      closed_at        TEXT,
      close_price      TEXT,
      strategy_hash    TEXT NOT NULL DEFAULT '',
      entry_signal_key TEXT NOT NULL DEFAULT ''
  );
  CREATE INDEX IF NOT EXISTS idx_trades_symbol_status
      ON trades(symbol, status);
  CREATE INDEX IF NOT EXISTS idx_trades_closed_at
      ON trades(closed_at) WHERE status = 'closed';
  """,
)
```

- `REFERENCES bot_runs(run_id)` matches the existing FK pattern.
- Decimal values stored as TEXT (consistent with `fills.size`, `fills.price`).
- Two indexes: one for `get_open_trade(symbol)` (hot path), one for the
  daily-loss aggregation query (filter by `closed_at` date).

---

## Integration points

### `AccountEventHandler` — gains `TradeLedger`

**File:** `finbot/core/application/use_cases/account_event_handler.py` (modified)

```python
class AccountEventHandler:
    def __init__(self, repo: BotStateRepository,
                 trade_ledger: TradeLedger | None = None): ...
        # ledger defaults to TradeLedger(repo) for backward compat
        self._trade_ledger = trade_ledger or TradeLedger(repo)

    def _handle_fill(self, order_id, event, *, bot_run_id, symbol):
        # ... existing duplicate check ...
        with tx():   # existing transaction
            if not self._apply_fill_transition(...): return ...
            fill = self._build_fill_record(...)
            self._repo.record_fill(fill)
            self._trade_ledger.apply_fill(fill)   # NEW: inside same tx
        return {"status": "processed"}
```

The Trade update is **inside the existing transaction** (ADR-6) — atomic with
the fill record and lifecycle advance. A crash between them cannot
double-count.

**Lazy construction site (important):** `LiveTradingRuntimeUseCase` builds
the handler lazily in `process_account_event`:
```python
if self._account_handler is None:
    self._account_handler = AccountEventHandler(self._repo)
```
Change that line to pass the ledger through:
```python
if self._account_handler is None:
    self._account_handler = AccountEventHandler(self._repo, self._trade_ledger)
```
The runtime already holds `self._trade_ledger` (added in the previous
section), so no new dependency lookup is needed.

### `LiveTradingRuntimeUseCase._build_risk_context` — real daily loss

**File:** `finbot/core/application/use_cases/live_trading_runtime.py` (modified)

```python
def _build_risk_context(self, bar, position):
    return {
        ...,
        # WAS: "daily_loss_usd": Decimal("0"),  # the bug
        "daily_loss_usd": self._trade_ledger.realized_loss_on(
            datetime.now(UTC).date()
        ),
    }
```

The runtime gains a `trade_ledger: TradeLedger` constructor dependency.
(Inline `datetime.now(UTC).date()` — there is no `now_utc_date()` helper.)

### `LiveTradingRuntimeUseCase.reconcile_on_startup` — NEW method (C2)

**File:** `finbot/core/application/use_cases/live_trading_runtime.py` (modified)

This method **does not exist today**; you create it. It is called once at
the start of `run_forever()`, after the `_started` check and before
`bot_loop.start(...)`:

```python
def reconcile_on_startup(self) -> ReconciliationRecord:
    """Fetch the exchange position; reconstruct an open Trade if one is
    open on the exchange but missing from the DB."""
    position = self._exchange.get_position(self._symbol)
    existing = self._repo.get_open_trade(self._symbol)
    if position.direction != PositionDirection.FLAT and existing is None:
        trade = self._trade_ledger.reconstruct_open(
            position, bot_run_id=self._bot_run_id,
            strategy_hash=self._strategy_hash,
        )
        self._repo.open_trade(trade)
    record = ReconciliationRecord(
        bot_run_id=self._bot_run_id,
        position_matches=(existing is not None)
                         or (position.direction == PositionDirection.FLAT),
        open_orders_match=True,   # placeholder; full order reconcile is later
        details=f"startup: exchange={position.direction.value} "
                f"db_open={'yes' if existing else 'no'}",
    )
    self._repo.record_reconciliation(record)
    return record
```

Note: `get_position` returns a FLAT `PositionSnapshot` when there is no
position — never `None`. Mismatches (exchange long / DB short) are flagged
in `details`, not auto-corrected.

### `LiveTradingRuntimeUseCase._dispatch_submission` — dry-run fill synthesis (C1)

**File:** `finbot/core/application/use_cases/live_trading_runtime.py` (modified)

The dry-run path must synthesize a fill so the ledger is fed (see ADR-8).
The change is in the DRY_RUN branch of `_dispatch_submission`:

```python
if self._mode == TradingMode.DRY_RUN:
    self._exchange.submit_order(intent)
    # NEW: synthesize a fill so the TradeLedger tracks the position.
    # Live/testnet do NOT do this — real fills arrive via the account stream.
    fill = self._synthesize_fill(intent, intent_id)
    if fill is not None:
        self._trade_ledger.apply_fill(fill)
    return intent_id, False
```

`_synthesize_fill` builds a `FillRecord` from the intent using the latest
bar's close as the fill price (already available as
`self._warmup.latest_bar`). fill_id is derived from the intent_id so it is
idempotent across replays. Side comes from `intent.side` (buy/sell).

---

## DTOs (new)

All in `finbot/core/domain/dto/`, one per file:

| DTO | Fields | Used by |
|-----|--------|---------|
| `FillOutcome` | status, position_id, realized_pnl | `TradeLedger.apply_fill` return |

(Only one new DTO — this is a small, focused spec.)

---

## Files to Add / Modify

### New files
| File | Layer |
|------|-------|
| `finbot/core/domain/entities/trade.py` | domain |
| `finbot/core/domain/services/trade_lifecycle.py` | domain |
| `finbot/core/domain/services/trade_ledger.py` | domain |
| `finbot/core/domain/dto/fill_outcome.py` | domain |
| `tests/test_domain/test_trade.py` | tests |
| `tests/test_domain/test_trade_lifecycle.py` | tests |
| `tests/test_domain/test_trade_ledger.py` | tests |
| `tests/test_domain/test_daily_loss_gate_functional.py` | tests |
| `tests/test_application/test_daily_loss_gate_e2e.py` | tests |
| `tests/test_application/test_reconciliation_reconstructs_trade.py` | tests |
| `tests/test_application/test_dry_run_order_simulation.py` (extend) | tests |
| `tests/test_infrastructure/test_sqlite_trade_repository.py` | tests |

### Modified files
| File | Change |
|------|--------|
| `finbot/core/domain/interfaces/bot_state_repository.py` | +6 Trade methods |
| `finbot/infrastructure/repositories/in_memory_bot_state_repository.py` | implement |
| `finbot/infrastructure/repositories/sqlite_bot_state_repository.py` | implement + `trades` mapping |
| `finbot/infrastructure/repositories/sqlite_migrator.py` | migration v3 |
| `finbot/core/application/use_cases/account_event_handler.py` | inject `TradeLedger`, call in tx; update lazy construction site |
| `finbot/core/application/use_cases/live_trading_runtime.py` | inject `TradeLedger`; real `daily_loss_usd`; NEW `reconcile_on_startup()`; NEW `_synthesize_fill()` on dry-run path |
| `finbot/core/domain/services/risk_gates/daily_loss_gate.py` | fix docstring (realized-only); **ADD exit-bypass** for LONG_EXIT/SHORT_EXIT |
| `finbot/startup/service_factory.py` | wire `TradeLedger` into the runtime + event handler |
| `finbot/core/domain/services/bot_manager.py` | (if it constructs the event handler) pass ledger through |

### Unchanged
`PositionSnapshot`, `FillRecord`, `OrderLifecycle`, `OrderIntent`.

**Note:** `DailyLossGate` logic is **changed** in this spec — it gains
exit-bypass (LONG_EXIT/SHORT_EXIT) and a docstring correction to
"realized-only". Its core comparison logic is unchanged; it was simply
being fed zeroes before.
