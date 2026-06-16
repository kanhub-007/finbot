# Multi-Ticker Portfolio Runtime

## User Story

**As a** strategy operator,
**I want to** run one strategy across multiple tickers in a single Finbot
process with a shared risk budget,
**so that** I can deploy a portfolio of positions under one set of risk
controls, one exchange connection, and one audited state store — instead of
spawning and babysitting one OS process per symbol.

## Context

Finbot today runs **one ticker per instance**. Every per-symbol coupling is
hard-wired through the stack:

- `LiveTradingRuntimeUseCase` holds one `self._symbol`, one `WarmupWindow`,
  one `self._enriched_frame`, one `StrategyEvaluator`.
- `BotLoop.start(symbol, interval, ...)` takes a single symbol.
- `BotManager._guard_no_conflict()` rejects starting a second runtime.
- The MCP control-plane spec explicitly lists multi-bot as a Non-Goal.
- The README documents "run N processes" as the multi-ticker answer.

Running N processes works but delivers **none of the value that motivates
multi-ticker trading**: there is no shared risk budget (each process
independently fills up to its own cap), no cross-symbol data, N exchange
connections, N databases (or contention on one), and no unified audit view.

Freqtrade solves this in a single process: a throttled loop refreshes candle
data for a *pairlist*, a `DataProvider` caches per-pair DataFrames, one
strategy analyzes each pair, and a global `max_open_trades` caps the
portfolio. The trade-off is that freqtrade polls REST every candle and
concentrates logic in a 2,600-line god-class.

Finbot will adopt freqtrade's **portfolio model** (shared book, shared risk,
central per-symbol data state) while keeping its own **event-driven model**
(websocket push, queue serialization) and **Clean Architecture** (no god
class, domain purity, one-class-per-file, DI throughout). The result is a
`PortfolioTradingRuntimeUseCase` that coordinates N per-symbol
`SymbolPipeline`s behind a portfolio risk layer.

## Key decisions (please confirm or adjust)

### Decision 1 — Single-process, not a supervisor

We build one process that runs N symbols. A separate "fleet supervisor"
that launches N existing single-symbol processes is explicitly rejected for
the MVP because it cannot deliver a shared risk budget or cross-symbol data —
which are the stated motivation. (ADR-1.)

### Decision 2 — One strategy, N symbols (freqtrade model)

The MVP runs **one** strategy file across the whole symbol set. "Run
strategies on multiple tickers" is interpreted as "one strategy deployed
across multiple tickers." Assigning **different** strategies to different
symbol subsets is real but deferred to Slice 3 — it multiplies complexity
(per-symbol evaluator wiring, per-strategy hashes, mixed risk profiles) and
is not needed to prove the multi-ticker plumbing. (ADR-2.)

> ⚠️ **Confirm:** is "one strategy, many symbols" the right MVP, or do you
> need "many strategies, each on its own symbols" from day one? If the
> latter, Slice 1 grows substantially and 03-domain.md needs a
> strategy-to-symbol mapping.

### Decision 3 — Static symbol list for MVP

The active symbol set comes from configuration (`FINBOT_SYMBOLS=BTC,ETH,SOL`
or a list in settings). A `SymbolSetProvider` interface ships in Slice 1
with a single `StaticSymbolSetProvider`. Dynamic selection (volume-based,
spread-filtered, etc.) is Slice 3 — the interface is designed now so it is a
drop-in later. (ADR-3.)

### Decision 4 — Portfolio risk is the core primitive

Two new gates gate the **whole book**, ahead of the existing per-symbol gates:

- `MaxOpenPositionsGate(max_positions)` — total open positions across all
  symbols.
- `MaxGrossNotionalGate(max_gross_usd)` — sum of |notional| across all open
  positions plus the proposed entry.

These are `Must`. Per-symbol `MaxPositionGate` / `MaxOpenOrdersGate` remain
as a second tier so an operator can also cap exposure per ticker. (ADR-4.)

### Decision 5 — Event-driven model preserved

We keep the websocket-push + thread-safe-queue model (ADR-3 of the live
runtime spec). `BotEventLoop` is extended to subscribe to multiple symbols
and demux candles by symbol; `on_candle` becomes `on_candle(symbol, candle)`.
We do **not** adopt freqtrade's sleep-until-next-candle REST poll. (ADR-5.)

## Non-Goals

Things explicitly **not** built in this spec:

- **Multiple strategies in one process.** One strategy per portfolio runtime.
  See Decision 2; deferred to a later spec.
- **Web dashboard / streaming UI.** MCP `get_portfolio_status` polling
  remains the observation path (consistent with the MCP control-plane spec).
- **Cross-symbol informative data** (strategy reading another symbol's
  frame). Designed for (via `MarketDataProvider` in 03-domain.md) but shipped
  in Slice 3, not Slice 1.
- **Dynamic pairlists** (volume/spread/market-cap filters). Interface ships
  in Slice 1; first dynamic implementation is Slice 3.
- **Per-symbol intervals.** All symbols share one interval for the MVP.
  Mixed intervals add alignment complexity (when is "the tick"?).
- **Auto-restart / crash recovery of the runtime thread.** Same stance as
  the MCP control-plane spec: the operator restarts explicitly.
- **Reimplementing freqtrade's `Trade` god-model (2,161 lines).** We borrow
  the *concept* of a durable per-position Trade entity, not freqtrade's
  structure. Finbot's Trade stays a pure dataclass; lifecycle logic lives in
  a domain service.
- **Portfolio-level rebalancing / correlation / Kelly sizing.** Out of scope;
  this spec is about *running* N tickers safely, not *optimizing* a
  portfolio.

## Relationship to existing specs

- **`2026-06-12_live-yaml-trading-runtime`** — the single-symbol
  `LiveTradingRuntimeUseCase` is **preserved**. Its per-symbol pipeline is
  *extracted* into a `SymbolPipeline` that the new portfolio runtime
  composes. The single-symbol runtime remains a valid (degenerate
  one-symbol) configuration and keeps its tests green.
- **`2026-06-14_finbot-mcp-control-plane`** — its Non-Goal "multi-bot
  management (multiple tickers)" is lifted by this spec. `BotManager` is
  retargeted to own one `PortfolioTradingRuntimeUseCase` instead of one
  `LiveTradingRuntimeUseCase`. MCP tools gain a `symbols` dimension.
- **`2026-06-15_live-external-data-supply`** — orthogonal. External
  (derivatives) data supply composes per-symbol just like OHLCV; no
  conflict.
