# Review & Recommendation — Multi-Ticker Portfolio Runtime

**Status:** **DEFERRED (SHELVED)** — not abandoned.
**Date:** 2026-06-15
**Decision maker:** Operator (after complexity/needs assessment).

---

## Recommendation

**Do not implement this spec now.** Keep the spec files as a reference design
for a future revisit. Focus near-term effort on strengthening the existing
**single-symbol** runtime using a small subset of freqtrade ideas (separate
spec). If multiple tickers are needed before then, run separate Finbot
instances — the current "one process per symbol" model is adequate and safe.

---

## Why defer

### 1. Complexity is high and concentrated in risky edits

The spec touches ~50 files. The cost is not the file count — it is *where*
the changes land:

| Risk class | Count | Examples |
|---|---|---|
| **Breaking interface changes** | 4 | `BotLoop.start`, `BotStateRepository`, `ExchangeGateway`, `BotRun` |
| **SQLite migration on live data** | 1 | new `trades` table |
| **New threading surfaces** | several | shared `TradeBook` read by MCP thread, written by runtime thread |
| **New domain entities + services** | ~8 | `Trade`, `SymbolPipeline`, `TradeBook`, `TradeLifecycle`, 2 gates, `SymbolSetProvider` |

Each breaking interface ripples through every implementation and every test.
In a safety-critical trading codebase that is the most expensive class of
change. Realistic effort with proper Red→Green→Refactor: **~4–8 weeks**.

### 2. The stated need is satisfiable without it

The operator's goal — "run strategies on multiple tickers" — is met today by
running N Finbot processes with different `--symbol` and database paths. The
README already documents this. What multi-process *lacks* is a **shared risk
budget** and **cross-symbol data**. The question that decides whether the
spec is worth its cost is:

> *Do you need a single risk cap spanning all symbols, or is per-symbol risk
> adequate?*

If per-symbol risk is adequate (the current model), the portfolio runtime
delivers convenience but not safety — and convenience alone does not justify
4 breaking interface changes and a live-data migration.

### 3. Two separable capabilities were fused; only one may be wanted

| Capability | Value | Cost |
|---|---|---|
| **(A) Many runtimes, one process, one DB** | Convenience: `list_bots`, `stop_bot(id)`, same/different strategies on different symbols without OS processes | Moderate (~1–2 weeks) |
| **(B) Portfolio-level shared risk** | One `max_open_positions`/`max_gross_notional` across the book; aggregate view; whole-book kill switch | High (~3–6 weeks) — the bulk of the spec |

This spec fused (A)+(B). If only (A) is wanted, ~75% of the spec's cost is
unjustified. That decision should be made from real usage, not assumed.

---

## What is preserved (nothing is lost)

- The 5 spec files (`01-story` … `05-architecture`) remain as a **reference
  design**. They document the full architecture, scenarios, domain model, and
  ADRs should the work be revived.
- The **freqtrade concepts** that motivated it (portfolio risk budget,
  per-pair data cache, durable position entity, orphaned-exit safety) are
  re-evaluated below for *single-symbol* applicability — most of the
  independently-valuable ones survive the pivot and move to the new spec.

---

## Phased path (if/when revisited)

If multi-ticker becomes justified later, build in this order so no phase is
throwaway:

| Phase | Scope | Effort | Independently valuable? |
|---|---|---|---|
| **0** | Durable `Trade` entity + realized PnL | ~3–5 days | **Yes** — useful single-symbol today (see new spec) |
| **1** | Multi-instance `BotManager` (capability A) | ~1–2 weeks | Yes — multi-strategy/multi-ticker in one process |
| **2** | Portfolio runtime + shared risk (capability B) | ~3–6 weeks | Only if shared risk is confirmed needed |
| **3** | Dynamic pairlists, cross-symbol data, per-symbol strategy assignment | later | Optional |

Phases 0 and 1 are **reusable inside Phase 2** — not throwaway.

---

## Revisit triggers

Re-open this spec when **any** of these becomes true:

1. **A shared risk budget is required** — e.g. "across all my symbols, never
   more than $X notional / N positions exposed." Per-symbol caps are
   insufficient. → Phase 2 is justified.
2. **Operating many processes is painful in practice** — process supervision,
   aggregated status, shared connection limits become real operational
   friction. → Phase 1 (multi-instance manager) is justified, even without
   shared risk.
3. **A strategy needs cross-symbol data** — e.g. "trade ETH using BTC's
   indicator frame." Cannot be done across processes. → Phase 2/3
   (`MarketDataProvider`) is justified.
4. **Realized-PnL / position-lifecycle needs** (Phase 0) outgrow the
   single-symbol hardening spec and demand a portfolio ledger.

Until one of these triggers, the current single-symbol + multi-instance model
is the right trade-off.

---

## Status of related specs

- **`2026-06-14_finbot-mcp-control-plane`** — its Non-Goal "multi-bot
  management (multiple tickers)" **remains a non-goal**. This deferral
  reaffirms it.
- **New spec: single-symbol hardening** (`2026-06-15_single-symbol-hardening`
  or similar) — captures the freqtrade concepts that strengthen the current
  runtime without multi-ticker complexity. See the companion analysis.
