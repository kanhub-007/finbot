# Architecture Decisions — Multi-Ticker Portfolio Runtime

---

# ADR-1: Single-process multi-symbol runtime (not a process supervisor)

**Context:**
Finbot currently runs one ticker per process. The obvious "multi-ticker"
answer is to launch N processes (the README's documented approach). That is
mechanically simple and maximally isolated. But it cannot deliver the
portfolio properties that motivate multi-ticker trading in the first place:
there is no shared risk budget (each process fills independently to its own
cap), no cross-symbol data, N exchange connections, N databases, and no
unified audit view.

**Decision:**
Build a single-process runtime that runs N symbols behind one portfolio risk
layer, one exchange connection, and one state store. A "fleet supervisor"
launching N single-symbol processes is explicitly rejected for the MVP.

**Consequences:**
- A shared `max_open_positions` / `max_gross_notional_usd` caps the whole
  book — the core safety primitive multi-symbol demands.
- One websocket connection fans out to N symbol subscriptions (Hyperliquid's
  stream supports multiple subscriptions on one connection).
- One process crash loses all symbols (vs. process-per-symbol where one crash
  loses one). Mitigated by: per-symbol isolation within the loop (ADR-6),
  startup reconciliation (ADR-7), and the kill switch.
- Shared in-process state requires thread-safety discipline (already
  established by `BotManager`'s lock + queue model).

---

# ADR-2: One strategy applied to a symbol set (freqtrade model)

**Context:**
"Run strategies on multiple tickers" is ambiguous: it can mean (a) one
strategy deployed across N tickers, or (b) M strategies each on its own
symbol subset. freqtrade chose (a) — one strategy, one `analyze()` loop over
the whitelist. finbot's current model is "one strategy file per runtime",
which maps cleanly onto (a).

**Decision:**
The MVP runs **one** strategy file across the whole symbol set. Each symbol
gets its own `StrategyEvaluator` instance (created via the existing factory,
parameterised by symbol), but all from the same definition. Per-symbol
strategy assignment (model b) is deferred to Slice 3.

**Consequences:**
- Slice 1 stays focused: the hard problem is the *multi-ticker plumbing*
  (demux, portfolio risk, reconciliation), not strategy assignment.
- The `SymbolPipeline` is designed so each pipeline can hold a different
  evaluator without structural change — Slice 3 is a wiring change, not a
  refactor.
- ⚠️ **Confirm this interpretation.** If model (b) is required from day one,
  Slice 1 grows a strategy-to-symbol map and mixed risk profiles; this ADR
  and 03-domain.md must be revised.

---

# ADR-3: Static symbol set for MVP; `SymbolSetProvider` interface ships now

**Context:**
The active symbol set could be static (config) or dynamic (volume-filtered,
spread-filtered, market-cap-ranked — freqtrade's pairlist plugins). Dynamic
selection is powerful but adds a refresh/lifecycle dimension and a new class
of edge cases (a symbol drops mid-position → orphaned exit).

**Decision:**
Ship a `SymbolSetProvider` Strategy interface in Slice 1 with a single
`StaticSymbolSetProvider` implementation. Dynamic providers are Slice 3. The
interface is designed now (`symbols()`, `refresh()`) so a dynamic impl is a
drop-in.

**Consequences:**
- MVP operators configure `FINBOT_SYMBOLS=BTC,ETH,SOL`.
- Orphaned-exit safety (S13) is still built in Slice 2 because even a static
  set can change across restarts, and it is a prerequisite for dynamic
  pairlists anyway.

---

# ADR-4: Portfolio risk gates sit ahead of per-symbol gates

**Context:**
Existing gates (`MaxPositionGate`, `MaxOpenOrdersGate`, `DailyLossGate`,
`MaxLeverageGate`, `ReduceOnlyGate`, `StaleDataGate`, `DuplicateSignalGate`,
`ModeGate`) are per-symbol — they read `self._symbol`-scoped context.
Multi-symbol requires book-wide limits ("at most 5 positions total", "at most
$5000 gross notional total") or the portfolio can be filled to the per-symbol
cap on every symbol simultaneously, defeating the purpose.

**Decision:**
Add two portfolio-scoped gates — `MaxOpenPositionsGate` and
`MaxGrossNotionalGate` — that read `portfolio_*` context fields. Wire them at
the **front** of the existing gate chain so a book-wide rejection short-
circuits before per-symbol checks. Per-symbol gates remain as a second tier
(to cap individual tickers).

**Consequences:**
- The gate chain order becomes: `[portfolio] → [per-symbol] → submit`.
- Exit signals (LONG_EXIT, SHORT_EXIT) bypass `MaxOpenPositionsGate` and
  `MaxGrossNotionalGate` — exits reduce exposure and must never be locked out
  by a "portfolio full" state, or the book can never unwind.
- Portfolio context must be rebuilt **per candle** (open-position count and
  gross notional change with every fill), not cached at start.

---

# ADR-5: Preserve the event-driven model; extend BotLoop to demux by symbol

**Context:**
freqtrade uses a throttled loop that polls REST for all pairs every candle
boundary (`Worker._throttle` aligned to `timeframe_to_next_date`). It is
simple and deterministic but adds latency and burns REST quota. finbot is
event-driven: websocket callbacks enqueue `BotEvent`s; the runtime processes
them serially on one thread (ADR-3 of the live runtime spec). Adopting
freqtrade's poll model would discard finbot's latency and reconnect
advantages and rewrite the loop.

**Decision:**
Keep the websocket-push + thread-safe-queue model. Extend `BotLoop.start` to
accept a `symbols: list[str]` and an `on_candle(symbol, candle)` callback.
`BotEventLoop` subscribes once per symbol on the shared `MarketDataStream`
and tags each candle with its symbol before enqueuing. The portfolio runtime
demultiplexes `(symbol, candle)` to the right `SymbolPipeline`.

**Consequences:**
- Low latency and real-time fills preserved.
- The single-threaded processing discipline is retained (one thread drains
  the queue; portfolio context is consistent within a candle's handling).
- The `BotLoop` interface change is breaking but contained — all call sites
  are internal to finbot.
- We borrow from freqtrade only its **discipline** ("one logical tick per
  closed candle, process the relevant symbol's pipeline"), not its loop.

---

# ADR-6: Per-symbol isolation inside the single-threaded loop

**Context:**
One process running N symbols means one symbol's failure must not take down
the others. A bad candle, a parse error, or a transient stream error for ETH
must not stop BTC and SOL.

**Decision:**
Each `process_closed_candle(symbol, candle)` call is wrapped so exceptions
are caught per-symbol: the offending pipeline is marked `degraded`, the
error is logged and audit-recorded, and the loop continues with the next
event. `symbol_status(symbol)` reports `ok` / `degraded`. A degraded symbol's
open positions are still protected by startup reconciliation on the next
restart and by the kill switch.

**Consequences:**
- No symbol can crash the portfolio runtime.
- Operators see per-symbol health in `portfolio_status()`.
- Recovery (reconnect) flips `degraded` back to `ok` automatically.

---

# ADR-7: Reconcile ALL symbols on startup; flag mismatches, never auto-close

**Context:**
finbot rule #6: "Database state is not authoritative by itself." Single-symbol
reconciliation fetches one position. Multi-symbol must fetch all, and must
reconstruct `Trade` entities for positions opened by a previous (crashed)
session so portfolio risk can count them.

**Decision:**
On startup, fetch positions AND open orders for every symbol in the set. For
each exchange-detected open position, reconstruct an open `Trade` (side/size/
entry from the snapshot; entry_price best-effort). Persist a
`ReconciliationRecord` per symbol. Mismatches (exchange has a position for an
unknown symbol; DB has an order the exchange no longer shows) are written to
the audit log. **Nothing is auto-closed** — the operator decides via the kill
switch.

**Consequences:**
- Portfolio risk counts are correct immediately after restart.
- No silent position assumption ("the DB says flat, so we're flat").
- An unexpected exchange position for a symbol not in the set is flagged,
  not acted on — preventing accidental closes of manually-managed positions.

---

# ADR-8: New durable `Trade` entity (distinct from PositionSnapshot)

**Context:**
finbot has `PositionSnapshot` (transient, read from the exchange each candle)
and `OrderIntent` / `FillRecord` (event rows). It has no durable concept of
"an open position with a lifecycle" — entry, trailing extremes, exit,
realized PnL. Multi-symbol amplifies the need: portfolio gates must count
open positions; exits must target the right one; PnL must persist across
candles and restarts.

**Decision:**
Add a `Trade` domain entity (pure frozen dataclass) persisted to a new
`trades` SQLite table. Lifecycle transitions (entry fill, exit fill, MFE/MAE
update, realized PnL) live in pure functions in a `TradeLifecycle` domain
service. `TradeBook` is the read/write ledger facade over the repository.

**Naming:** `Trade` (not `Position`) avoids collision with the existing
`PositionSnapshot` / `PositionDirection`. A trade = the durable lifecycle
record of one position. This matches freqtrade's `Trade` concept without
importing its 2,161-line anemic-but-fat model — finbot's `Trade` is a pure
dataclass; all logic is in `TradeLifecycle`.

**Consequences:**
- Portfolio gates query `TradeBook.count_open()` / `gross_notional()`.
- Exits match a `Trade` by symbol; partial fills update size without closing.
- `PositionSnapshot` remains the transient exchange read; `Trade` is the
  durable domain truth. Reconciliation reconciles the two.
- A mapper separates `Trade` (domain) from `TradeOrm` (SQLite).

---

# ADR-9: `SymbolPipeline` extraction preserves the single-symbol runtime

**Context:**
The per-symbol pipeline (warmup → enrich → validate → evaluate → risk → plan
→ persist → submit) is currently embedded in `LiveTradingRuntimeUseCase`.
Multi-symbol needs it parameterised by symbol and instantiated N times. A
risky option is to rewrite `LiveTradingRuntimeUseCase` in place.

**Decision:**
Extract the per-symbol body into a `SymbolPipeline` domain service. Keep
`LiveTradingRuntimeUseCase` as a thin holder of one pipeline (a degenerate
single-symbol portfolio) so its existing tests stay green throughout the
refactor. The new `PortfolioTradingRuntimeUseCase` composes N pipelines.

**Consequences:**
- The refactor is behaviour-preserving and verifiable: the single-symbol test
  suite must pass unchanged after extraction.
- `MarketDataProvider` (Slice 3) can later hoist per-symbol state out of
  pipelines without touching their contract (pipelines already expose
  `warmup_count` / `enriched_frame` / `is_ready`).
- Two runtime use cases coexist until the single-symbol one is retired
  (optional, post-Slice-3).

---

# ADR-10: Borrow freqtrade's portfolio *model*, not its structure

**Context:**
freqtrade has solved multi-pair trading at scale. But its structure is an
anti-pattern by finbot's constitution: `FreqtradeBot` is a 2,647-line god
class, `Trade` is 2,161 lines mixing data and logic, and exchange/strategy/
persistence concerns are interleaved.

**Decision:**
Adopt freqtrade's *ideas* — portfolio risk budget (`max_open_trades`), a
central per-pair data cache, per-pair dedup, orphaned-exit safety, durable
per-position entity. Do **not** adopt its structure. Map every idea onto
finbot's Clean Architecture: one class per file, DI throughout, pure domain
entities, domain interfaces for swappable behaviour (Strategy/Chain-of-Resp
for gates and pairlists), mappers between domain and ORM.

**Consequences:**
- finbot gains freqtrade's portfolio capabilities without its
  maintainability debt.
- Each borrowed idea is re-expressed in finbot's layering and tested with
  Classical-school black-box tests per AGENTS.md §3.
- The mapping is explicit (see README "Decisions to confirm" + each ADR).
