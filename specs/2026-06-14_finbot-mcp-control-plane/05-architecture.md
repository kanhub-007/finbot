# Architecture Decisions — Finbot MCP Control Plane

---

## ADR-1: MCP Uses FastMCP (Same as finbar/kapsula)

**Context:** Finbar and Kapsula both use `fastmcp` (FastMCP) for their MCP
servers. Alternatives considered: raw `mcp` library, custom implementation.

**Decision:** Use `fastmcp>=2.0.0` as an optional dependency, following the
exact same pattern as finbar and kapsula.

**Consequences:**
- Consistent developer experience across all three projects.
- FastMCP provides decorator-based `@mcp.tool()` registration, HTTP + stdio
  transports, and Claude Desktop integration out of the box.
- Optional dependency means `finbot` CLI works without `fastmcp` installed.

---

## ADR-2: BotManager Lives in core/domain/services/

**Context:** The `BotManager` orchestrates `LiveTradingRuntimeUseCase`,
`BotStateRepository`, and `ExchangeGateway` — all domain interfaces. Where
should it live?

Options considered:
- `infrastructure/services/` — but BotManager has no SDK/framework deps
- `core/application/use_cases/` — but it's not a single use case; it's a
  service that owns lifecycle across multiple use-case invocations
- `core/domain/services/` — it depends only on domain interfaces + Python stdlib

**Decision:** Place `BotManager` in `core/domain/services/` because:
1. It depends only on domain interfaces (`BotStateRepository`, `ExchangeGateway`)
   and the stdlib (`threading`, `time`, `pathlib`).
2. It receives the concrete `LiveTradingRuntimeUseCase` factory via
   constructor injection — no direct dependency.
3. It is testable with only fakes.

**Consequences:**
- Clean Architecture boundaries are preserved.
- The MCP tools in `presentation/mcp/tools/` access `BotManager` via the
  FastMCP instance (injected at startup), not via a global.
- `BotManager` can be tested in isolation with fakes.

---

## ADR-3: One Bot at a Time (Single Instance)

**Context:** The user confirmed "1 bot is 1 trading strategy on 1 ticker,
for now this can be kept as is."

**Decision:** `BotManager` manages exactly one bot instance. Starting a second
bot while one is running returns a "bot already running" error. Multi-bot
support is a future consideration.

**Consequences:**
- Simpler implementation: no need for a registry of bots, no per-bot naming,
  no concurrent resource management.
- `get_bot_status` always refers to the one running bot (or the last completed
  run).
- The constraint is documented in tool descriptions so MCP users know the
  limitation.

---

## ADR-4: Runtime Runs in Background Thread, Not Process

**Context:** `LiveTradingRuntimeUseCase.run_forever()` blocks. The MCP server
also blocks on `server.run()`. We need concurrency.

Options considered:
- **Separate process** (`multiprocessing`): Isolates crashes, but complicates
  state sharing (needs IPC, serialization).
- **Background thread** (`threading`): Simple state sharing via shared memory,
  but a runtime crash takes down the whole process.
- **Async runtime**: Major refactor of `LiveTradingRuntimeUseCase` to be async.

**Decision:** Use `threading.Thread` (daemon). The runtime runs in a daemon
thread; the MCP server runs on the main thread. State is shared via a
thread-safe `BotLiveState` container.

**Consequences:**
- Simple: no serialization, no IPC, no async refactor.
- A runtime crash kills the whole process (daemon thread + main thread
  share fate). Acceptable for now — the operator restarts the MCP server.
- Python GIL means the runtime thread and MCP thread share CPU time, but
  MCP requests are infrequent and the runtime's heavy work is I/O-bound
  (websocket reads, HTTP calls) where the GIL is released.
- The `stop_bot` tool joins the thread with a 5s timeout to prevent hanging.

---

## ADR-5: MCP Tools Return JSON Strings

**Context:** `fastmcp` tools can return Python dicts (auto-serialized) or
strings. Finbar tools return JSON strings.

**Decision:** Follow the finbar pattern: all tools return `json.dumps(result,
indent=2)` as strings. This gives full control over formatting and avoids
FastMCP's auto-serialization edge cases.

**Consequences:**
- Consistent with finbar and kapsula codebases.
- `indent=2` makes output human-readable in MCP clients.
- Slightly more verbose code (explicit `json.dumps` in every tool body).

---

## ADR-6: MCP Server Uses Instance Storage for BotManager, Not Module Global

**Context:** Finbar's MCP tools access dependencies via `_shared.py` module-level
lazy factories. Kapsula uses the same pattern. Both work but make testing harder
because module state persists across tests.

**Decision:** Store `BotManager` as an attribute on the FastMCP server instance
(e.g., `server._finbot_bot_manager`). Tools access it via a helper that reads
from the current server context.

**Consequences:**
- Tests can create a fresh FastMCP server per test, each with its own
  `BotManager` (wired with fakes).
- No module-level state to reset between tests.
- Slightly different from finbar's pattern, but justified by testability.

---

## ADR-7: New Repository Query Methods Added to Existing Interface

**Context:** The MCP tools need historical queries: `list_bot_runs`,
`get_signals_for_run`, `get_orders_for_run`, `get_fills_for_run`,
`get_risk_events_for_run`, `get_audit_log`.

**Decision:** Add these as abstract methods to the existing
`BotStateRepository` interface in `core/domain/interfaces/`. Implement in
both `InMemoryBotStateRepository` and `SqliteBotStateRepository`.

**Consequences:**
- Single interface for all bot state — no separate "read repository."
- Both implementations must implement all new methods (increases surface
  area slightly).
- This is CQRS-lite: reads still go through the repository interface,
  which is acceptable for moderate-volume queries (status checks, run
  history browsing).

---

## ADR-8: No REST API — MCP Is the Sole Programmatic Interface

**Context:** Finbot currently has a CLI. Adding MCP gives a programmatic
interface. Should we also add a REST API?

**Decision:** No REST API for now. MCP is the programmatic interface. The
CLI remains for direct terminal use. If REST is needed later, it would be
a separate concern with its own ADRs.

**Consequences:**
- MCP tools must cover all the functionality an operator needs remotely.
- The CLI and MCP tools share the same underlying use cases via the
  composition root.
- Reduces maintenance burden (one programmatic interface, not two).
