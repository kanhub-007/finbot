# Finbot MCP Control Plane

**Date:** 2026-06-14
**Cynefin classification:** Complicated — the components (FastMCP server,
BotManager, thread-safe state, MCP tool registration) are individually
well-understood from finbar/kapsula patterns, but assembling them while
preserving Clean Architecture boundaries and thread safety requires
careful integration.

## Root Cause

Finbot currently only has a CLI interface. To monitor and control a running
bot, the operator must SSH into the machine and use terminal commands. There
is no programmatic interface for an AI assistant or remote client to:

- Start/stop a bot in different modes (dry-run, testnet, live)
- Inspect the current bot state (position, last signal, last candle)
- Review historical results from completed runs
- Trigger emergency stop/cancel

MCP (Model Context Protocol) is the standard interface for AI assistants.
Finbar and Kapsula already provide MCP servers using FastMCP. Finbot should
do the same.

## Summary

Add an MCP server that allows:

1. **Start a bot** — dry-run, testnet, or live mode, with YAML strategy, symbol, interval
2. **Stop a bot** — graceful shutdown with thread joining
3. **Get bot status** — live state snapshot (position, last signal, candle counts)
4. **List completed runs** — historical run summaries
5. **Get run results** — detailed signals, orders, fills, risk events for a run
6. **Validate strategy** — check a YAML file before running
7. **Emergency panic** — stop bot + cancel orders + optionally close position
8. **Health check** — server uptime, exchange connectivity

The MCP server runs on the main thread. The bot runtime runs in a daemon
background thread. State is shared via a thread-safe `BotLiveState` container.

The architecture follows the exact same pattern as finbar and kapsula:
`startup/mcp.py` composition root → `presentation/mcp/tools/` tool modules →
`run_mcp.py` entry point.

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Background thread for runtime (not process) | Simple state sharing, no IPC overhead; Python GIL not a bottleneck (I/O-bound workload) |
| `BotManager` in `core/domain/services/` | Depends only on domain interfaces + Python stdlib — framework-independent |
| Factory callable for runtime construction | `BotManager` stays unaware of `startup/service_factory.py` wiring details |
| One bot at a time | User confirmed constraint: "1 bot = 1 strategy on 1 ticker" |
| `BotManager` on FastMCP instance, not module global | Enables per-test fresh server instances with fakes |
| `fastmcp>=2.0.0` as optional dependency | Doesn't bloat core install; consistent with finbar/kapsula |
| JSON string returns from tools | Full control over formatting; consistent with finbar pattern |

## Files

- `01-story.md` — user story, context, non-goals
- `02-scenarios.md` — 10 scenarios across 4 slices, with Gherkin, I/O tables, Verify blocks
- `03-domain.md` — entities, new DTOs, BotManager, BotLiveState, interface changes
- `04-implementation.md` — 14-step implementation guide for a junior developer
- `05-architecture.md` — 8 architecture decision records (ADRs)
