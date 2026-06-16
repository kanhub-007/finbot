# Multi-Ticker Portfolio Runtime

**Status:** Draft — awaiting confirmation of the decisions flagged below.
**Created:** 2026-06-15
**Supersedes (partially):** `2026-06-14_finbot-mcp-control-plane` Non-Goal
"Multi-bot management (multiple strategies, multiple tickers simultaneously)."
This spec lifts the **multiple tickers** dimension of that non-goal.

## One-line summary

Run **one strategy across a set of tickers in a single process**, with a
portfolio-level risk budget, shared exchange connection, and per-symbol
state — instead of one OS process per symbol.

## Documents

| File | Contents |
|------|----------|
| `01-story.md` | User story, context, key decisions to confirm, non-goals |
| `02-scenarios.md` | 18 scenarios (MoSCoW) with Gherkin, I/O tables, Verify blocks |
| `03-domain.md` | New `Trade` entity, `SymbolPipeline`, portfolio gates, interfaces |
| `04-implementation.md` | Step-by-step build order, sliced |
| `05-architecture.md` | ADRs: single-process vs supervisor, event model, portfolio risk |

## Decisions to confirm before implementation

These are the foundational choices. Each is made with a recommended default
and documented as an ADR in `05-architecture.md`. Flip any of them and the
spec is revised accordingly.

1. **Single-process multi-symbol (Option B)** — not a multi-process supervisor.
2. **One strategy applied to a symbol set** (freqtrade model). Per-symbol
   strategy assignment is Slice 3 / out of scope for the MVP.
3. **Static configured symbol list for MVP.** A `SymbolSetProvider` interface
   ships in Slice 1 with one static implementation; dynamic pairlists are
   Slice 3.
4. **Portfolio-level risk is the core value:** `max_open_positions` and
   `max_gross_notional_usd` gate the whole book. Per-symbol caps are retained
   as a second tier.
5. **Event-driven model preserved.** Finbot keeps its websocket + queue model
   (ADR-3 of the live runtime spec); we add per-symbol demux. We do **not**
   adopt freqtrade's REST-poll-every-candle model.
