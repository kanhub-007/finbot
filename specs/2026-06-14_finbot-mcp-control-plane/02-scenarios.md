# Scenarios — Finbot MCP Control Plane

Scenarios are ordered by MoSCoW priority and implementation slice. Tests must
use Classical-school, black-box style: real domain objects, in-memory fakes
for boundaries, and outcome assertions.

---

## Slice 1: MVP — Start/Stop/Status (Must)

---

### Scenario: Start dry-run bot via MCP
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the MCP server is running and no bot is active
  When the user calls `start_bot` with a valid strategy path, symbol, interval, and mode="dry_run"
  Then a new bot run is created, the runtime starts in a background thread, and the tool returns the bot_run_id and status "running"

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| strategy_path | string | `tests/fixtures/strategies/amt_dip_buyer_final.yaml` | Required, file must exist, must be valid YAML |
| symbol | string | `"BTC"` | Required, non-empty |
| interval | string | `"1h"` | Required, valid Hyperliquid interval |
| mode | string | `"dry_run"` | Must be one of: dry_run, testnet, live |
| warmup_bars | int | `100` | Optional, min warmup bars; default 100 |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Returns JSON with bot_run_id and status="running" | Parse tool response |
| Calling `get_bot_status` returns active bot with correct strategy/symbol/interval/mode | Status tool response matches inputs |
| Runtime thread is alive | `get_bot_status` shows is_running=True |
| No orders submitted to exchange (dry-run) | Fake exchange gateway.submitted_order_count == 0 after several candles |

**Verify (Classical school, black-box):**
```python
from finbot.startup.mcp_for_test import create_test_server

mcp_tools = create_test_server()  # wires InMemoryExchangeGateway, fake stream

result = mcp_tools.call("start_bot", strategy_path=STRATEGY_PATH, symbol="BTC",
                        interval="1h", mode="dry_run", warmup_bars=0)
data = json.loads(result)
assert data["status"] == "running"
assert data["bot_run_id"]

# Bot is running in background thread
status = json.loads(mcp_tools.call("get_bot_status"))
assert status["is_running"] is True
assert status["mode"] == "dry_run"
assert status["symbol"] == "BTC"

mcp_tools.call("stop_bot")
```

**Also test:**
- Invalid strategy path → returns error, bot not started
- Strategy with unsupported features → rejected (in live/testnet mode)
- Starting a second bot while one is running → returns error "bot already running"
- warmup_bars=0 → starts immediately, warmup fills from live data

---

### Scenario: Get bot status via MCP when no bot is running
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the MCP server is running and no bot is active
  When the user calls `get_bot_status`
  Then the tool returns is_running=False and summary of the last completed run

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| (none) | — | — | No parameters |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| is_running is False | Parse response |
| Returns summary of last completed run (if any) | Check last_run field |
| Returns null/empty when no runs exist | Check last_run is null |

**Verify (Classical school, black-box):**
```python
mcp_tools = create_test_server()
result = json.loads(mcp_tools.call("get_bot_status"))
assert result["is_running"] is False
assert result["last_run"] is None  # fresh repo, no history
```

---

### Scenario: Get bot status via MCP while bot is running
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a bot is running in dry-run mode and has processed at least one candle
  When the user calls `get_bot_status`
  Then the tool returns is_running=True with current position, last candle timestamp, last signal action, last order status, and counts

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| (none) | — | — | No parameters |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| is_running is True | Parse response |
| bot_run_id matches the started run | Compare with start_bot return |
| strategy_name, symbol, interval, mode are present | Check fields |
| last_candle_timestamp is present and non-zero | Assert int > 0 |
| last_signal_action is "hold", "long_entry", "short_entry", "long_exit", "short_exit", or None | Check enum values |
| last_signal_timestamp is present if signal processed | Check field |
| total_signals >= 0, total_orders >= 0, total_fills >= 0 | Check counts |
| open_position_size is present (Decimal) | Check type |

**Verify (Classical school, black-box):**
```python
mcp_tools = create_test_server()
mcp_tools.call("start_bot", strategy_path=STRATEGY_PATH, symbol="BTC",
                interval="1h", mode="dry_run", warmup_bars=0)

# Feed a candle and wait for processing
fake_stream = mcp_tools._bot_manager._bot_loop._stream
fake_stream.emit_closed_candle(make_candle(close=42000))
time.sleep(0.2)  # let background thread process

status = json.loads(mcp_tools.call("get_bot_status"))
assert status["is_running"] is True
assert status["last_candle_timestamp"] > 0
# signal could be HOLD or ENTRY depending on strategy — both are valid
assert status["last_signal_action"] in (None, "hold", "long_entry", "short_entry")
assert status["total_signals"] >= 0

mcp_tools.call("stop_bot")
```

**Also test:**
- Status immediately after start (before first candle) → is_running=True, last_candle_timestamp=0
- Status during warmup → reports warmup progress

---

### Scenario: Stop a running bot via MCP
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a bot is running in dry-run mode
  When the user calls `stop_bot`
  Then the runtime stops, the background thread is joined, the bot run end marker is persisted, and the tool confirms the bot has stopped

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| (none) | — | — | No parameters |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Returns JSON with status="stopped" | Parse response |
| get_bot_status shows is_running=False | Follow-up query |
| Bot run end marker persisted | Check fake repository |
| Background thread is no longer alive | Thread check |

**Verify (Classical school, black-box):**
```python
mcp_tools = create_test_server()
mcp_tools.call("start_bot", strategy_path=STRATEGY_PATH, symbol="BTC",
                interval="1h", mode="dry_run", warmup_bars=0)

result = json.loads(mcp_tools.call("stop_bot"))
assert result["status"] == "stopped"

status = json.loads(mcp_tools.call("get_bot_status"))
assert status["is_running"] is False
assert status["last_run"] is not None  # the run we just stopped
```

**Also test:**
- stop_bot when no bot is running → returns status="no_bot_running", no error
- Calling stop_bot twice → second call is idempotent, no crash

---

### Scenario: Start testnet/live bot requires explicit acknowledgment
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the MCP server is running with testnet or live mode configured
  When the user calls `start_bot` with mode="testnet" or mode="live" without live_trading_ack=true
  Then the tool rejects the start and returns an error explaining the acknowledgment requirement

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| mode | string | `"testnet"` | testnet or live |
| live_trading_ack | bool | `false` | Default false |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Returns JSON with status="rejected" | Parse response |
| Error message mentions live_trading_ack | Check message field |
| No bot is started | get_bot_status shows is_running=False |

**Verify (Classical school, black-box):**
```python
mcp_tools = create_test_server(testnet=True)
result = json.loads(mcp_tools.call("start_bot", strategy_path=STRATEGY_PATH,
    symbol="BTC", interval="1h", mode="testnet", live_trading_ack=False))
assert result["status"] == "rejected"
assert "live_trading_ack" in result["message"].lower()

status = json.loads(mcp_tools.call("get_bot_status"))
assert status["is_running"] is False
```

**Also test:**
- testnet mode with live_trading_ack=true → accepted
- live mode with live_trading_ack=true → accepted
- live mode with missing private key → rejected with clear message

---

## Slice 2: Historical Results & Run Listing (Should)

---

### Scenario: List completed bot runs
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given the repository has multiple completed bot runs
  When the user calls `list_bot_runs`
  Then the tool returns a list of all bot runs with run_id, strategy, symbol, interval, mode, start/end timestamps, and signal/order/fill counts

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| limit | int | `10` | Optional, default 20, max 100 |
| mode | string | `"dry_run"` | Optional, filter by mode |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Returns JSON array of run summaries | Parse response |
| Each run has run_id, strategy_name, symbol, interval, mode, started_at, ended_at | Check keys |
| Runs are ordered by most recent first | Check timestamps |
| Limit and mode filter work | Test with different values |

**Verify (Classical school, black-box):**
```python
mcp_tools = create_test_server()

# Pre-populate repo with some runs
for i in range(3):
    mcp_tools._bot_manager._repo.create_bot_run(
        BotRun(strategy_name=f"strat_{i}", symbol="BTC", interval="1h", mode="dry_run")
    )

result = json.loads(mcp_tools.call("list_bot_runs", limit=10))
assert len(result["runs"]) == 3
assert result["runs"][0]["strategy_name"] == "strat_2"  # most recent first
```

---

### Scenario: Get detailed results for a specific bot run
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given the repository has a completed bot run with signals and orders
  When the user calls `get_bot_run_results` with a valid run_id
  Then the tool returns the full run details including all signals, order intents, order responses, fills, and risk events

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| run_id | string | `"uuid-here"` | Required, must exist in repository |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Returns JSON with run summary and detailed arrays | Parse response |
| signals array contains signal_key, action, timestamp | Check array keys |
| orders array contains intent_id, status | Check array keys |
| risk_events array contains event_type, decision, reason | Check array keys |
| Returns error for nonexistent run_id | Test error path |

**Verify (Classical school, black-box):**
```python
mcp_tools = create_test_server()

# Start and stop a bot to create run history
mcp_tools.call("start_bot", strategy_path=STRATEGY_PATH, symbol="BTC",
                interval="1h", mode="dry_run", warmup_bars=0)

fake_stream = mcp_tools._bot_manager._bot_loop._stream
fake_stream.emit_closed_candle(make_candle(close=42000))
time.sleep(0.2)

start_result = json.loads(mcp_tools.call("stop_bot"))
# The last run is now in the repo

results = json.loads(mcp_tools.call("get_bot_run_results",
    run_id=status_result["last_run"]["run_id"]))
assert "run" in results
assert "signals" in results
assert "risk_events" in results
```

**Also test:**
- Nonexistent run_id → error "run not found"

---

### Scenario: Get run summary with P&L-like metrics
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given the repository has a completed bot run with fills
  When the user calls `get_bot_run_results` for that run
  Then the response includes summary metrics: total signals, total orders, total fills, and basic trade metrics

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| run_id | string | `"uuid-here"` | Required |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| summary includes signal_count, order_count, fill_count | Check keys |
| summary includes start_time, end_time, duration_seconds | Check keys |
| trade_count derived from fills | Check value |

**Verify (Classical school, black-box):**
```python
mcp_tools = create_test_server()
# Pre-populate with known data
run = BotRun(strategy_name="test", symbol="BTC", interval="1h", mode="dry_run")
mcp_tools._bot_manager._repo.create_bot_run(run)
mcp_tools._bot_manager._repo.mark_signal_processed(
    ProcessedSignal(signal_key="key1", bot_run_id=run.run_id, signal_action="long_entry", bar_timestamp="1000"))
mcp_tools._bot_manager._repo.mark_signal_processed(
    ProcessedSignal(signal_key="key2", bot_run_id=run.run_id, signal_action="long_exit", bar_timestamp="2000"))

result = json.loads(mcp_tools.call("get_bot_run_results", run_id=run.run_id))
assert result["summary"]["signal_count"] == 2
```

---

## Slice 3: Lifecycle & Safety (Should)

---

### Scenario: MCP server health check / ping
**Priority:** Should
**Slice:** 3

**Gherkin:**
  Given the MCP server is running
  When the user calls `ping`
  Then the tool returns server status, uptime, and whether the Hyperliquid connection is healthy

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| (none) | — | — | No parameters |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Returns JSON with status="ok" | Parse response |
| uptime_seconds is a positive number | Check field |
| hyperliquid_connected is true/false | Check field |

**Verify (Classical school, black-box):**
```python
mcp_tools = create_test_server()
result = json.loads(mcp_tools.call("ping"))
assert result["status"] == "ok"
assert result["uptime_seconds"] > 0
```

---

### Scenario: Configure and validate strategy before starting
**Priority:** Should
**Slice:** 3

**Gherkin:**
  Given the MCP server is running
  When the user calls `validate_strategy` with a strategy path
  Then the tool returns whether the strategy is valid, its name, timeframe, indicator count, and any errors

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| strategy_path | string | `tests/fixtures/strategies/amt_dip_buyer_final.yaml` | Required, file must exist |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| valid: true for valid strategies | Check field |
| returns strategy_name, primary_timeframe, indicator_count | Check fields |
| valid: false for invalid strategies, with errors array | Test invalid input |

**Verify (Classical school, black-box):**
```python
mcp_tools = create_test_server()
result = json.loads(mcp_tools.call("validate_strategy", strategy_path=VALID_STRATEGY_PATH))
assert result["valid"] is True
assert result["strategy_name"]

result = json.loads(mcp_tools.call("validate_strategy", strategy_path=INVALID_STRATEGY_PATH))
assert result["valid"] is False
assert len(result["errors"]) > 0
```

---

### Scenario: Emergency stop (panic cancel) via MCP
**Priority:** Should
**Slice:** 3

**Gherkin:**
  Given a bot is running in testnet or live mode
  When the user calls `panic` with cancel_orders=true
  Then the running bot is stopped, all open orders are cancelled via the exchange, and the result is returned

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| cancel_orders | bool | `true` | Default true |
| close_position | bool | `false` | Optional, default false |
| symbol | string | `"BTC"` | Required if close_position=true |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Bot is stopped | get_bot_status shows is_running=False |
| Returns cancel result from exchange | Check response |
| Orders cancelled count is reported | Check response fields |

**Verify (Classical school, black-box):**
```python
mcp_tools = create_test_server(testnet=True)
mcp_tools.call("start_bot", strategy_path=STRATEGY_PATH, symbol="BTC",
                interval="1h", mode="testnet", live_trading_ack=True)

result = json.loads(mcp_tools.call("panic", cancel_orders=True, symbol="BTC"))
assert "cancel" in result or result["bot_stopped"] is True

status = json.loads(mcp_tools.call("get_bot_status"))
assert status["is_running"] is False
```

**Also test:**
- Panic in dry-run mode → still stops bot, cancel is no-op (safe)
- Panic when no bot running → returns "no bot running", no error

---

## Slice 4: Enhanced Observability (Could)

---

### Scenario: Get recent audit log entries
**Priority:** Could
**Slice:** 4

**Gherkin:**
  Given the repository has audit log entries from bot runs
  When the user calls `get_audit_log` with optional limit and event_type filter
  Then the tool returns the most recent audit log entries in reverse chronological order

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| limit | int | `50` | Optional, default 50, max 500 |
| event_type | string | `"enrichment_validation_failed"` | Optional, filter by event type |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Returns JSON array of audit entries | Parse response |
| Each entry has bot_run_id, event_type, event_data_json, timestamp | Check keys |
| Most recent first | Check ordering |

---

### Scenario: Get candle processing history for current run
**Priority:** Could
**Slice:** 4

**Gherkin:**
  Given a bot is running and has processed multiple candles
  When the user calls `get_recent_candles` with optional limit
  Then the tool returns recent candle processing results with timestamps, signal actions, and risk decisions

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| limit | int | `20` | Optional, default 20, max 100 |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Returns JSON array of candle results | Parse response |
| Each entry has candle_timestamp, signal_action, risk_decision | Check keys |
| Returns empty array when no candle data | Check edge case |

---

## Summary — Tool Inventory

| Tool Name | Slice | Priority | Description |
|-----------|-------|----------|-------------|
| `start_bot` | 1 | Must | Start a bot with strategy/symbol/interval/mode |
| `stop_bot` | 1 | Must | Stop the currently running bot |
| `get_bot_status` | 1 | Must | Get live status of running bot or last run summary |
| `list_bot_runs` | 2 | Should | List completed bot runs with summaries |
| `get_bot_run_results` | 2 | Should | Get detailed results for a specific run |
| `validate_strategy` | 3 | Should | Validate a strategy file without starting a bot |
| `ping` | 3 | Should | Health check — server status and exchange connectivity |
| `panic` | 3 | Should | Emergency stop + cancel orders + optionally close position |
| `get_audit_log` | 4 | Could | Retrieve recent audit log entries |
| `get_recent_candles` | 4 | Could | Recent candle processing history for current run |

### Files to Create

| File | Layer | Purpose |
|------|-------|---------|
| `finbot/presentation/mcp/__init__.py` | Presentation | MCP tools package |
| `finbot/presentation/mcp/tools/__init__.py` | Presentation | Tool registration aggregator |
| `finbot/presentation/mcp/tools/bot_control.py` | Presentation | `start_bot`, `stop_bot`, `get_bot_status` tools |
| `finbot/presentation/mcp/tools/bot_history.py` | Presentation | `list_bot_runs`, `get_bot_run_results` tools |
| `finbot/presentation/mcp/tools/safety.py` | Presentation | `panic` tool |
| `finbot/presentation/mcp/tools/util.py` | Presentation | `ping`, `validate_strategy`, `get_audit_log` tools |
| `finbot/startup/mcp.py` | Startup | FastMCP composition root + BotManager |
| `run_mcp.py` | Root | Convenience entry point |

### Dependency Additions

Add to `pyproject.toml` under `[project.optional-dependencies]`:
```
mcp = ["fastmcp>=2.0.0"]
```
