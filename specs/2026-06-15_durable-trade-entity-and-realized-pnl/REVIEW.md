# Spec Self-Review — Findings & Gaps

**Status: ALL FINDINGS RESOLVED (2026-06-15).** The critical and significant
gaps below were fixed directly in the spec files. The spec is now ready for
implementation by a junior dev following Red→Green→Refactor. The findings
are retained for traceability; each is marked ✅ with the fix location.

**Original verdict (pre-fix):** NOT YET ready — three critical gaps would
stall or mislead implementation. All claims verified against the actual code
on 2026-06-15.

---

## CRITICAL — would block or silently mislead implementation

### C1. Scenario S10 is impossible as written (dry-run never produces fills)  ✅ FIXED

**The gap:**
`DryRunExchangeGateway.submit_order()` returns `{"status": "dry_run"}`
and emits **no fill event**. The bot loop is built with `account=False` for
dry-run (`service_factory.py`), so there is **no account stream**, so
`process_account_event` is never called, so `AccountEventHandler._handle_fill`
never runs, so `TradeLedger.apply_fill` is never called.

**Consequence:** in dry-run, **no Trade ever opens, no realized PnL is ever
booked, and the DailyLossGate STILL never fires** — defeating the spec's
central purpose in the one mode operators use for validation. It also
contradicts AGENTS.md ("dry-run must exercise the same risk path as live").

**Fix — pick one and state it as ADR-8:**
- **(a) Recommended:** have `LiveTradingRuntimeUseCase._dispatch_submission`
  synthesize a fill on the dry-run path and feed it to the ledger directly
  (the runtime owns both the dry-run submission and the ledger). Keeps the
  account handler unchanged; dry-run and live converge on the same
  `TradeLedger.apply_fill`.
- (b) Upgrade `DryRunExchangeGateway` to emit fill events through the queue —
  more moving parts, couples the gateway to the event queue.
- (c) Drop S10 and accept daily-loss works only in testnet/live — weakest,
  breaks dry-run/live parity.

S10's verify block must be rewritten to match the chosen path.

---

### C2. `runtime.reconcile_on_startup()` does not exist  ✅ FIXED

**The gap:**
S8's verify block calls `runtime.reconcile_on_startup()`. 03-domain.md and
04-implementation Step 9 say "extend `reconcile_on_startup`." **There is no
such method.** `run_forever()` just calls `bot_loop.start(...)`. The only
reconciliation today is a post-submit placeholder in `OrderSubmitter`
(`_record_reconciliation`), not startup reconciliation.

A junior dev has no anchor: the method they're told to extend isn't there.

**Fix:** Add a step before Step 9:
> **Step 8b: Add `reconcile_on_startup()` to `LiveTradingRuntimeUseCase`**
> and call it at the start of `run_forever()`, after the `_started` check,
> before `bot_loop.start(...)`. Signature: `reconcile_on_startup() ->
> ReconciliationRecord`. It fetches `self._exchange.get_position(symbol)`
  (returns a FLAT snapshot when no position — not None), and if direction !=
  FLAT with no open Trade in the DB, reconstructs one.

State explicitly that this is **new code**, not an extension.

---

### C3. `DailyLossGate` does NOT bypass exit signals — spec assumes it does  ✅ FIXED

**The gap:**
The current gate (verified) has zero exit-bypass:
```python
def check(self, signal, context) -> RiskDecision:
    if daily >= self._max:
        return RiskDecision(accepted=False, ...)   # rejects EVERYTHING
    return RiskDecision(accepted=True, ...)
```
If realized loss exceeds the cap, the gate would **reject LONG_EXIT /
SHORT_EXIT too** — locking the bot into losing positions so it can never
unwind to realize the loss. That's a safety inversion.

S5 ("exit signal evaluated when over cap → accepted") and Step 8
("test_gate_does_not_block_exit_signals") assume bypass exists. It does not.

**Fix:** Make it explicit in Step 8 that the dev must **ADD** exit-bypass
to `DailyLossGate`:
```python
if signal.action in (SignalAction.LONG_EXIT, SignalAction.SHORT_EXIT):
    return RiskDecision(accepted=True, gate_name="daily_loss",
                        reason="exits bypass daily-loss cap")
```
Call this out as a behaviour change, not a verification. `ReduceOnlyGate`
already proves the pattern (it checks `signal.action`).

---

## SIGNIFICANT — would confuse or stall a junior dev

### S1. Repository API is inconsistent: `close_trade` vs `update_trade`  ✅ FIXED

**The gap:**
- 03-domain.md interface defines `open_trade(trade)` + `update_trade(trade)`.
- 02-scenarios.md S2/S5/S6 verify blocks call `repo.close_trade(position_id=,
  close_price=, closed_at=, realized_pnl=)`.

Two different signatures for closing a Trade. The dev doesn't know which to
implement.

**Fix:** Standardize on `open_trade(trade)` + `update_trade(trade)` (the
frozen-entity-replace-row model — matches how `TradeLifecycle` produces new
immutable `Trade` instances). Remove `close_trade` from all verify blocks;
replace with `repo.update_trade(closed_trade)`. Update Step 4 test names.

### S2. `TradeLedger.reconstruct_open(position)` is referenced but undefined  ✅ FIXED

**The gap:** S8 and 03-domain.md mention it; no signature, no behaviour.

**Fix:** Define it in 03-domain.md:
```python
def reconstruct_open(self, position: PositionSnapshot, *, bot_run_id: str,
                     strategy_hash: str = "") -> Trade:
    """Build an open Trade from an exchange position with no fill history.
    entry_price=None (unknown), opened_at=now(UTC), size=abs(position.size),
    side=position.direction. Caller persists + records a ReconciliationRecord."""
```

### S3. `AccountEventHandler` is lazily constructed inside the runtime — wiring not addressed  ✅ FIXED

**The gap:** The spec says "inject TradeLedger into AccountEventHandler," but
the handler is built lazily in `process_account_event`:
`if self._account_handler is None: self._account_handler = AccountEventHandler(self._repo)`.

**Fix:** State explicitly: `LiveTradingRuntimeUseCase` gains a
`trade_ledger` constructor dep; when it lazily builds the handler it passes
both: `AccountEventHandler(self._repo, self._trade_ledger)`. Add to Step 6.

### S4. Audit fields `strategy_hash` / `entry_signal_key` have no population rule  ✅ FIXED

**The gap:** Decision 4 says "best-effort, may be empty" but doesn't say how
or whether to populate them in Slice 1.

**Fix:** State for Slice 1: populate `strategy_hash` from
`BotRun.strategy_hash` (available via `repo.get_bot_run(bot_run_id)`, or pass
through); leave `entry_signal_key=""` (deferred — needs cloid→intent lookup).
Or: leave both empty for Slice 1 and file a follow-up. Pick one, say it.

---

## MINOR / POLISH (junior-dev friction)

### M1. Several scenarios lack input tables (AGENTS.md §5 criterion violated)
Only ~1–2 of 12 scenarios have a proper `**Input table:**`. Add them to at
least S2, S5, S6 (the ones with non-trivial inputs). Others can reference
"same as S1."

### M2. Test helpers in Verify blocks are undefined
`entry_fill()`, `exit_fill()`, `buy_fill()`, `sell_fill()`, `make_fill()`,
`entry_signal()`, `now_utc()`, `entry_signal_candle()` are used but never
defined. Add a one-line note at the top of 02-scenarios.md: *"Test helpers
(`buy_fill`, `entry_signal`, …) are `FillRecord`/`SignalDecision` factories
you write; signature mirrors the entity."* Or provide one example factory.

### M3. `now_utc_date()` is referenced as a helper
It's just `datetime.now(UTC).date()`. Inline it in the code samples to avoid
a hunt.

### M4. Typo in S3 verify block
`assert trade.size == Decimal("01")` → should be `Decimal("0.1")`.

### M5. S1 "Also test" mentions "two symbols independent" — leftover from the multi-ticker spec
This is a single-symbol spec. Rephrase to "a second Trade opens after the
first closes on the same symbol" or remove.

### M6. `realized_loss_on` exists on both repo and ledger
Clarify: the runtime calls **`trade_ledger.realized_loss_on(day)`**, which
delegates to `repo.realized_loss_on(day)`. State the call site once to avoid
"which one do I call?" confusion.

### M7. Migration placement not pinned
State: "append the v3 tuple to the end of the `MIGRATIONS` list in
`sqlite_migrator.py` (after the v2 entry). `LATEST_VERSION` auto-updates
via `max(v for v, _ in MIGRATIONS)`."

### M8. `sign_for` vs `sign(side)` naming inconsistency
03-domain.md lists `sign_for(side)` in TradeLifecycle but the PnL formula
uses `sign(side)`. Standardize on `sign_for`.

### M9. Gate chain order nuance
`DailyLossGate` runs before `DuplicateSignalGate` and `ReduceOnlyGate` in the
wired chain. Note that exit-bypass (C3) sees the raw `signal.action`, which
is correct. One sentence suffices.

---

## AGENTS.md §5 quality checklist

| Criterion | Status |
|-----------|--------|
| Each scenario has clear Gherkin | ✅ all 12 |
| Input table defines types + constraints | ❌ ~10 of 12 missing (M1) |
| Verify block shows Classical-school test | ✅ all 12 |
| "Also test" lists edge cases | ✅ most |
| MoSCoW priority clear | ✅ all |
| Ambiguous language | ⚠ a few (C1/C2/C3 are the big ones) |
| Self-contradictory | ❌ repo API (S1) |
| Domain entities have field types | ✅ Trade fully specified |
| Interfaces have method signatures | ⚠ `reconstruct_open` missing (S2) |
| Entity vs ORM separation noted | ✅ |

---

## Recommendation

**Do not hand to a junior dev yet.** Resolve C1–C3 first (they're design
decisions + explicit anchors, ~1–2 hours of spec edits), then S1–S4
(signature standardization, ~30 min). The minor items (M1–M9) are polish
that can be batched.

After those fixes the spec is implementable by a junior dev following
Red→Green→Refactor, because every step will have: a precise file, a precise
signature, a verify command, and an unambiguous expected outcome. Today,
Steps 6, 8, 9, 10 each have at least one hidden "figure it out yourself."

The **core design is sound** (Trade entity, TradeLifecycle pure functions,
realized-only loss, UTC day window, atomic fill handling). The gaps are in
specification precision, not architecture.

---

## Suggested edit order (when revisiting)

1. Decide C1 (dry-run fill synthesis) → add ADR-8, rewrite S10 + Step 10.
2. Fix C2 → add Step 8b (new `reconcile_on_startup` method + call site).
3. Fix C3 → Step 8 explicitly adds exit-bypass code to DailyLossGate.
4. Fix S1 → standardize on `open_trade`/`update_trade`; scrub `close_trade`.
5. Fix S2 → define `reconstruct_open` signature + behaviour.
6. Fix S3/S4 → wiring + audit-field rules in Step 6.
7. Batch M1–M9 polish.
