# Finbot MCP Control Plane

## User Story

As a Finbot operator, I want to control and observe a live Finbot trading
runtime through MCP (Model Context Protocol) tools — start/stop bots in dry-run,
testnet, or live mode, inspect the current bot state (position, last signal,
last candle, risk decisions), and review historical results from completed
runs — so that I can monitor and manage trading from an AI assistant or any
MCP-compatible client without SSH or CLI access.

## Context

Finbot currently has a CLI (`finbot.presentation.cli.main`) that supports
`run`, `status`, `validate-strategy`, `replay`, `panic`, and `db migrate`.
The `run --live-data` command starts a `LiveTradingRuntimeUseCase` that blocks
the main thread via `run_forever()`. The `status` command prints a one-off
snapshot of the most recent signal/order/fill counts.

Finbar and Kapsula already provide MCP servers using the `fastmcp` library
(FastMCP). They follow Clean Architecture with a dedicated composition root
at `startup/mcp.py`, tool registration in `presentation/mcp/tools/`, and a
convenience entry point `run_mcp.py`. Finbot should adopt the same pattern.

The key architectural challenge is that `LiveTradingRuntimeUseCase.run_forever()`
blocks the thread. For MCP to work, the runtime must run in a background thread
while the MCP server stays responsive on the main thread. The MCP tools need
thread-safe access to the runtime's current state and to the persistent
repository for historical queries.

The design follows Finbot's constraint: **1 bot = 1 trading strategy on 1
ticker**. The MCP control plane manages a single bot instance at a time. Future
iterations may add multi-bot management, but that is explicitly out of scope.

### Current Architecture Reference

```
presentation/
├── cli/main.py          # argparse CLI (run, status, validate, replay, panic, db)
├── mcp/                 # (DOES NOT EXIST YET — this spec creates it)
│   ├── tools/           # MCP tool modules
│   └── __init__.py
startup/
├── mcp.py               # (DOES NOT EXIST YET — FastMCP composition root)
├── service_factory.py   # existing factory functions
└── db.py                # existing DB helpers
run_mcp.py               # (DOES NOT EXIST YET — convenience entry point)
```

## Non-Goals

Things explicitly not being built in this iteration:

- Multi-bot management (multiple strategies, multiple tickers simultaneously).
  The constraint "1 bot = 1 strategy on 1 ticker" is preserved.
- Web dashboard or REST API for bot control.
- Bot auto-restart on crash — the MCP user must explicitly restart.
- Modifying a running bot's strategy or ticker without stopping and restarting.
- Persisting bot state across process restarts beyond what the SQLite
  repository already stores (bot_runs, signals, orders, fills).
- Real-time streaming of candle-by-candle results through MCP (MCP is
  request/response, not streaming). Periodic polling via `get_bot_status`
  is the intended pattern.
- Backtesting from MCP — use the CLI `replay` command or Finbar for that.
- Configuration hot-reload — settings come from environment variables at
  startup and do not change while the MCP server is running.
