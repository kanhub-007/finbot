# Scenarios — Durable Trade Entity & Realized PnL

Scenarios ordered by MoSCoW, grouped into Slices. Each has Gherkin, an I/O
table, expected state, and a Classical-school black-box Verify block using
`InMemoryBotStateRepository` and fake fill events. No mocks of domain
objects.

**Conventions (per AGENTS.md §3):**

- Real domain objects; `InMemoryBotStateRepository` at the boundary.
- Assert on **outcomes** (persisted Trade state, gate decisions), never
  `assert_called` on domain interfaces.
- A fake `TradeLedger` is never needed — test the real one against the
  in-memory repo.

**Test helpers used in Verify blocks** are small factories you write in
the test module; they are not part of the spec. Their signatures mirror
the entities exactly:
```python
from datetime import UTC, datetime
from decimal import Decimal

def make_fill(*, symbol="BTC", side="buy", size, price, fee="0",
              fill_id="f1", filled_at=None) -> FillRecord: ...   # size/price: str|Decimal
def buy_fill(*, size, price, **kw) -> FillRecord:  return make_fill(side="buy",  size=size, price=price, **kw)
def sell_fill(*, size, price, **kw) -> FillRecord: return make_fill(side="sell", size=size, price=price, **kw)
def now_utc() -> datetime: return datetime.now(UTC)
def entry_signal(*, symbol="BTC") -> SignalDecision: ...  # action=LONG_ENTRY
```
`entry_fill`/`exit_fill` in S2 are just `buy_fill`/`sell_fill` renamed for
readability. Write each helper once at the top of the test file.

---

# Slice 1 — MVP (all Must)

Proves: a Trade opens on entry, closes on exit with realized PnL, persists,
survives restart, and the daily-loss gate actually blocks.

---

### Scenario S1: Entry fill opens a Trade
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given no open Trade exists for "BTC"
  When  a buy fill of size 0.1 at price 50000 arrives
  Then  a new Trade is created with side=long, status=open
  And   entry_price=50000, size=0.1, opened_at=fill time
  And   it is persisted and queryable by symbol

**Input table:**
| Field    | Type     | Example  | Constraints             |
|----------|----------|----------|-------------------------|
| symbol   | str      | "BTC"    | non-empty               |
| side     | str      | "buy"    | buy \| sell             |
| size     | Decimal  | 0.1      | > 0                     |
| price    | Decimal  | 50000    | > 0                     |
| fee      | Decimal  | 0.5      | >= 0                    |
| fill_id  | str      | "f1"     | unique (idempotency)    |
| filled_at| datetime | now(UTC) | timezone-aware UTC      |

**Expected output / state change:**
| Assertion                                    | How to verify                          |
|----------------------------------------------|----------------------------------------|
| One open Trade for BTC                       | `repo.get_open_trade("BTC")` not None  |
| side LONG, status open, entry_price 50000    | inspect Trade fields                   |

**Verify (Classical school, black-box):**
```python
repo = InMemoryBotStateRepository()
ledger = TradeLedger(repo)

ledger.apply_fill(make_fill(symbol="BTC", side="buy", size=Decimal("0.1"),
                            price=Decimal("50000"), fee=Decimal("0.5"),
                            fill_id="f1"))

trade = repo.get_open_trade("BTC")
assert trade is not None
assert trade.side == PositionDirection.LONG
assert trade.status == "open"
assert trade.entry_price == Decimal("50000")
assert trade.size == Decimal("0.1")
assert trade.opened_at is not None
```

**Also test:**
- sell fill opens a SHORT trade
- a second Trade opens only after the first closes on the same symbol
  (two simultaneous open Trades for one symbol is NOT allowed — see S9)

---

### Scenario S2: Exit fill closes a Trade with realized PnL
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given an open long Trade for BTC (entry 50000, size 0.1)
  When  a sell fill of size 0.1 at price 51000 arrives (reduce-only exit)
  Then  the Trade is closed: status=closed, close_price=51000, closed_at set
  And   realized_pnl = (51000 - 50000) * 0.1 - fees = 100 - fees

**Input table:**
| Field     | Type     | Example  | Constraints                              |
|-----------|----------|----------|------------------------------------------|
| side      | str      | "sell"   | buy \| sell; must oppose the open Trade  |
| size      | Decimal  | 0.1      | > 0; <= open Trade size (reduce-only)    |
| price     | Decimal  | 51000    | > 0                                      |
| fee       | Decimal  | 0.5      | >= 0                                     |
| open trade| Trade    | long BTC | the Trade this fill closes (precondition)|

**Verify:**
```python
ledger.apply_fill(entry_fill(price=50000, size="0.1", side="buy", fee="0.5"))
ledger.apply_fill(exit_fill(price=51000, size="0.1", side="sell", fee="0.5"))

closed = repo.list_closed_trades()
assert len(closed) == 1
t = closed[0]
assert t.status == "closed"
assert t.close_price == Decimal("51000")
assert t.realized_pnl == Decimal("99")             # (51000-50000)*0.1 - 0.5 - 0.5
assert repo.get_open_trade("BTC") is None          # no longer open
```

**Also test:**
- short exit: entry sell 50000, exit buy 49000 → pnl = (50000-49000)*0.1 - fees = 100 - fees
- losing trade: long entry 50000, exit 49000 → realized_pnl = -100 - fees (negative)

---

### Scenario S3: Partial fills accumulate and partially close
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given no open Trade
  When  two buy fills arrive (0.05 @ 50000, 0.05 @ 52000)
  Then  one Trade accumulates: size 0.1, entry_price = avg = 51000
  When  a partial sell fill of 0.04 @ 53000 arrives
  Then  the Trade stays open with size 0.06 and realizes partial pnl for the 0.04 closed

**Verify:**
```python
ledger.apply_fill(buy_fill(size="0.05", price="50000"))
ledger.apply_fill(buy_fill(size="0.05", price="52000"))

t = repo.get_open_trade("BTC")
assert t.size == Decimal("0.1")
assert t.entry_price == Decimal("51000")           # weighted average

ledger.apply_fill(sell_fill(size="0.04", price="53000"))

t = repo.get_open_trade("BTC")
assert t is not None and t.status == "open"
assert t.size == Decimal("0.06")                   # reduced, not closed
# realized PnL for the 0.04 portion is booked on a closed "partial" record
# (see ADR-4: realized PnL accrues per closed portion)
```

> **Design decision (resolved):** Model (a) is chosen — a single Trade row
> whose `realized_pnl` accrues as exits fill, staying `open` until size hits
> 0. So `realized_pnl` means "PnL realized *so far* on this Trade" while open,
> and "final realized PnL" once closed. The `daily_loss` query sums only
> `status='closed'` rows (see 03-domain.md `realized_loss_on`), so a partial
> close does NOT trip the daily gate until the Trade fully closes. This is
> the conservative choice — document it in the gate docstring.

**Also test:**
- final exit fill closes the Trade (size → 0, status closed)
- entry fills at same price do not change avg

---

### Scenario S4: Realized PnL sign correct for long and short
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a long trade entered at 50000
  When  it exits at 49000
  Then  realized_pnl is negative (a loss)
  Given a short trade entered at 50000
  When  it exits at 49000
  Then  realized_pnl is positive (a profit)

**Verify:**
```python
# long loss
ledger.apply_fill(buy_fill(price="50000", size="1"))
ledger.apply_fill(sell_fill(price="49000", size="1"))
assert repo.list_closed_trades()[-1].realized_pnl < 0

# short profit
ledger.apply_fill(sell_fill(price="50000", size="1"))
ledger.apply_fill(buy_fill(price="49000", size="1"))
assert repo.list_closed_trades()[-1].realized_pnl > 0
```

---

### Scenario S5 (THE BUG FIX): DailyLossGate blocks after realized loss
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given max_daily_loss_usd = 25
  And   a closed trade today realized -30 USD loss
  When  a new LONG_ENTRY signal is evaluated
  Then  the DailyLossGate rejects it
  And   the rejection reason cites the loss vs the cap

**Verify:**
```python
repo = InMemoryBotStateRepository()
# Seed a closed losing trade realized today, using update_trade
# (the frozen-entity replace-row API; there is no close_trade method).
from datetime import UTC, datetime
trade = Trade(
    position_id="p1", bot_run_id="run1", symbol="BTC",
    side=PositionDirection.LONG, size=Decimal("0"),   # fully closed
    entry_price=Decimal("50000"), opened_at=now_utc(),
    status="closed", realized_pnl=Decimal("-30"),     # realized -30 USD
    close_price=Decimal("47000"), closed_at=now_utc(),
)
repo.open_trade(trade)   # insert the pre-built closed Trade directly
# (in a real run TradeLedger.apply_fill builds the closed Trade; here we
#  seed it directly to isolate the gate test.)

from datetime import date
gate = DailyLossGate(max_loss_usd=Decimal("25"))
ctx = {"daily_loss_usd": repo.realized_loss_on(now_utc().date())}   # = 30
decision = gate.check(entry_signal(), ctx)

assert decision.accepted is False
assert decision.gate_name == "daily_loss"
```

**Also test:**
- realized loss 20 < cap 25 → entry accepted
- no closed trades today → daily_loss_usd 0 → accepted (even if yesterday lost)
- **exit signal evaluated when over cap → accepted.** The current gate has
  NO exit bypass (verified) — it would reject LONG_EXIT/SHORT_EXIT too,
  locking the bot into losing positions. **You must ADD bypass** (Step 8):
  ```python
  if signal.action in (SignalAction.LONG_EXIT, SignalAction.SHORT_EXIT):
      return RiskDecision(accepted=True, gate_name="daily_loss",
                          reason="exits bypass daily-loss cap")
  ```
  This is a behaviour change, not a verification. The pattern is already
  used by `ReduceOnlyGate`, which inspects `signal.action`.

---

### Scenario S6: Daily loss window resets at UTC midnight
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a closed trade yesterday realized -100 USD loss
  When  a new entry signal is evaluated today (after 00:00 UTC)
  Then  the gate does NOT count yesterday's loss
  And   the entry is accepted (assuming no loss today)

**Verify:**
```python
# Seed a loss that closed YESTERDAY using update_trade (frozen replace-row).
yesterday = now_utc() - timedelta(days=1)
trade = Trade(
    position_id="p2", bot_run_id="run1", symbol="BTC",
    side=PositionDirection.LONG, size=Decimal("0"),
    entry_price=Decimal("50000"), opened_at=yesterday - timedelta(hours=1),
    status="closed", realized_pnl=Decimal("-100"),
    close_price=Decimal("49000"), closed_at=yesterday,
)
repo.open_trade(trade)

loss_today = repo.realized_loss_on(now_utc().date())
assert loss_today == Decimal("0")              # yesterday excluded
gate = DailyLossGate(max_loss_usd=Decimal("25"))
assert gate.check(entry_signal(), {"daily_loss_usd": loss_today}).accepted
```

**Also test:**
- a loss at 23:59 UTC and another at 00:01 UTC are in different days
- trades closed across the boundary sum correctly per day

---

### Scenario S7: Trade persisted and queryable across restart
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a bot run with one open and two closed trades
  When  the process restarts and the repository is reopened
  Then  list_open_trades returns the one open trade
  And   list_closed_trades returns the two with their realized_pnl intact

**Verify:**
```python
# Use the SQLite repo to prove durability (in-memory proves logic only)
repo = SqliteBotStateRepository(tmp_db_path)
migrator = SqliteMigrator(tmp_db_path); migrator.migrate()
# ... open/close trades via ledger ...
repo.close()

repo2 = SqliteBotStateRepository(tmp_db_path)
assert len(repo2.list_open_trades()) == 1
closed = repo2.list_closed_trades()
assert len(closed) == 2
assert all(t.realized_pnl is not None for t in closed)
```

---

### Scenario S8: Restart reconciliation reconstructs an open Trade
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the process restarts with no open Trade in the DB
  But   the exchange reports an open BTC long position (size 0.1)
  When  startup reconciliation runs
  Then  a Trade is reconstructed: side=long, size=0.1, status=open
  And   entry_price is best-effort (unknown if no fill history) and flagged
  And   a ReconciliationRecord is persisted

**Verify:**
```python
fake_exchange.get_position = lambda s: PositionSnapshot(
    symbol="BTC", direction=PositionDirection.LONG, size=Decimal("0.1"))
# reconcile_on_startup is a NEW method you add in Step 8b (it does not exist
# in the codebase today). It is called once at the start of run_forever().
rec = runtime.reconcile_on_startup()

assert repo.get_open_trade("BTC") is not None     # reconstructed
assert repo.get_open_trade("BTC").side == PositionDirection.LONG
assert repo.get_open_trade("BTC").entry_price is None  # unknown → left None
assert isinstance(rec, ReconciliationRecord)
```

**Also test:**
- exchange flat, DB has open trade → trade kept; record notes the match
- exchange long, DB open short → mismatch flagged (not auto-corrected)

---

### Scenario S9: Fill idempotency — replayed fill does not double-count
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a fill with fill_id "f1" was already applied (opened a Trade)
  When  the same fill_id "f1" is delivered again (reconnect/replay)
  Then  it is detected as a duplicate and skipped
  And   the Trade is not opened twice and size is not doubled

**Verify:**
```python
ledger.apply_fill(make_fill(fill_id="f1", side="buy", size="0.1", price="50000"))
result = ledger.apply_fill(make_fill(fill_id="f1", side="buy", size="0.1", price="50000"))

assert result.status == "duplicate"
trades = repo.list_open_trades()
assert len(trades) == 1
assert trades[0].size == Decimal("0.1")          # not doubled
```

**Also test:**
- replayed exit fill does not re-close / double-realize PnL

---

### Scenario S10: Dry-run mode still tracks Trades
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the bot runs in dry_run mode
  When  a strategy entry signal is accepted
  Then  the runtime synthesizes a fill from the accepted intent and feeds it
        to the TradeLedger, opening a Trade
  When  a later exit signal is accepted and its fill is synthesized
  Then  the Trade closes with realized PnL
  So that daily-loss protection works identically in dry-run and live

> **Why this needs special handling:** the `DryRunExchangeGateway`
> returns `{"status":"dry_run"}` and emits **no fill**, and dry-run builds
> with `account=False` (no account stream). So `AccountEventHandler` is
> never called and no Trade would ever open. The runtime must synthesize a
> fill on the dry-run path (ADR-8) so the ledger is fed. Live/testnet do
> NOT do this — real fills arrive via the account stream.

**Verify:**
```python
runtime = build_runtime(mode=TradingMode.DRY_RUN)   # in-memory repo, fake stream
runtime.process_closed_candle(entry_signal_candle())
assert repo.get_open_trade("BTC") is not None        # synthesized fill opened it

runtime.process_closed_candle(exit_signal_candle())
assert len(repo.list_closed_trades()) == 1
```

> **Rationale:** dry-run must exercise the same risk path as live (AGENTS.md
> rule: "dry-run evidence is weak if logic differs"). The daily-loss gate
> must protect dry-run too.

---

# Slice 2 — Should

---

### Scenario S11: Trade history query with PnL summary
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given several closed trades across a run
  When  the operator queries trade history
  Then  closed trades are returned newest-first with realized_pnl
  And   a summary total_realized_pnl is computed

**Verify:**
```python
history = repo.list_closed_trades(bot_run_id=run_id)
assert history == sorted(history, key=lambda t: t.closed_at, reverse=True)
total = sum(t.realized_pnl for t in history)
```

---

### Scenario S12: Daily-loss context wired into the runtime (end-to-end)
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given the runtime is running and a trade closed today at -30 USD loss
  When  the next candle produces an entry signal
  Then  the runtime's risk context carries the real daily_loss_usd (-30)
  And   the OrderPlanner chain rejects the entry via DailyLossGate
  And   a risk event "rejected / daily_loss" is persisted

**Verify:**
```python
# End-to-end through the real runtime + in-memory repo + fake exchange
runtime.process_closed_candle(candle_closing_at_loss())   # realizes -30
result = runtime.process_closed_candle(next_entry_signal_candle())

assert result.risk_decision == "rejected"
events = repo.get_risk_events_for_run(run_id)
assert any(e.event_type == "daily_loss" and e.decision == "rejected" for e in events)
```

---

## Coverage of the confirmed gap

| Gap (from freqtrade study) | Closed by |
|----------------------------|-----------|
| `DailyLossGate` reads hardcoded 0, never blocks | S5, S6, S12 |
| No durable position concept | S1, S7, S8 |
| No realized PnL | S2, S3, S4 |
| Fills are orphan events (no aggregation) | S1–S3, S9 |

## Coverage of AGENTS.md trading safety rules

| Rule | Covered by |
|------|------------|
| Persist before/after external effects | S1, S2 (Trade open/close around fill, atomic — ADR-6) |
| Reconcile on startup | S8 |
| Reduce-only exits | S2 (exit fills reduce; enforced by ReduceOnlyGate upstream) |
| Risk gates before every order | S5, S12 (DailyLossGate now functional) |
| Dry-run = live path | S10 |
