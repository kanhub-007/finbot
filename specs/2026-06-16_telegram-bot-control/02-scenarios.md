# Scenarios — Telegram Bot Control

> **UI flows are written from the Telegram user's perspective.**
> Bot responses use MarkdownV2 formatting.
> `[text]` denotes an inline keyboard button.

## Global implementation clarifications

- Telegram authorization **fails closed**. If `FINBOT_TELEGRAM_ENABLED=true` but
  no `FINBOT_TELEGRAM_ALLOWED_USERS` are configured, only `/whoami` is allowed.
  All control commands (`/run`, `/stop`, `/status`, `/panic`, `/history`, `/list`)
  return an authorization/setup error.
- `/whoami` is available to everyone and returns the Telegram `user_id` and
  `chat_id`; this is how the operator discovers the ID to put into `.env`.
- Callback data must **not** carry full strategy names and full state because
  Telegram callback data is limited to 64 bytes. Use short callback payloads with
  a server-side run-flow session store keyed by `(chat_id, message_id)` or a
  short `session_id`.
- `HandleTelegramCommand` returns a `TelegramCommandResult`. It does **not** send
  Telegram messages directly. `presentation/telegram/bot_handler.py` is the only
  code that replies/edits Telegram messages.
- PnL and mark-price fields are optional in MVP. If the current repository/state
  cannot compute them, omit those lines or show `PnL: unavailable`.
- Slice 1 scenarios require black-box tests with fakes for the Telegram adapter,
  chat repository, strategy directory, session store, and bot manager.

---

## Slice 1 — MVP (Must Have)

---

### Scenario: User registers with /start
**Priority:** Must
**Slice:** 1

**Telegram UI flow:**
```
User:  /start

Bot:   🤖 *Finbot Trading Bot*
       Connected to Hyperliquid\. Manage your trading strategies from here\.

       *Commands:*
       /run — Start a trading bot
       /stop — Stop the running bot
       /status — View bot status & stats
       /history — Browse past runs
       /panic — Emergency stop \+ cancel orders
       /help — Show this message

       [Run Bot] [Status] [History] [Help]
```

**Gherkin:**
  Given the Telegram bot is running and the user is in the allowed-users list
  When  the user sends `/start`
  Then  the bot responds with a welcome message listing all available commands
  And   the response includes an inline keyboard with shortcuts for main actions
  And   the user's chat ID is persisted for future notifications

**Input table:**
| Field    | Type   | Example        | Constraints          |
|----------|--------|----------------|----------------------|
| chat_id  | int    | 123456789      | From Telegram update |
| user_id  | int    | 987654321      | From Telegram update |
| command  | str    | "/start"       | Must be "/start"     |

**Expected output / state change:**
| Assertion                                          | How to verify                        |
|----------------------------------------------------|--------------------------------------|
| Response text contains "Finbot Trading Bot"        | Inspect returned message text        |
| Response includes inline keyboard with 4+ buttons  | Inspect reply_markup                 |
| Chat ID is stored in chat repository               | repo.get_chat(chat_id) is not None   |
| Repeated /start returns same welcome (no error)    | Second call succeeds                 |

**Also test:**
- User not in allowed-users list → "Unauthorized" message, no persistence
- Empty allowed-users list with enabled Telegram → setup/auth error; user is told to run `/whoami` and configure `FINBOT_TELEGRAM_ALLOWED_USERS`
- `/start` with no arguments works (no crash)

**Verify (Classical school, black-box):**
```python
fake_repo = InMemoryTelegramChatRepository()
fake_manager = FakeBotManager()
fake_sessions = InMemoryTelegramSessionStore()

use_case = HandleTelegramCommand(
    bot_manager=fake_manager,
    chat_repo=fake_repo,
    strategy_dir=FakeStrategyDirectory([]),
    session_store=fake_sessions,
    allowed_users={987654321},
    live_trading_ack=False,
)

result = await use_case.execute(TelegramCommandRequest(
    command="/start",
    args="",
    chat_id=123456789,
    user_id=987654321,
))

assert result.text is not None
assert "Finbot Trading Bot" in result.text
assert result.reply_markup is not None
assert len(result.reply_markup.inline_keyboard) >= 1
assert fake_repo.get_chat(123456789) is not None
```

---

### Scenario: User discovers their Telegram ID with /whoami
**Priority:** Must
**Slice:** 1

**Telegram UI flow:**
```
User:  /whoami

Bot:   Your Telegram IDs:
       User ID: 987654321
       Chat ID: 123456789

       Add this to your environment:
       FINBOT_TELEGRAM_ALLOWED_USERS=987654321
```

**Gherkin:**
  Given the Telegram bot is running
  When  any user sends `/whoami`
  Then  the bot responds with the Telegram user_id and chat_id from the update
  And   no authorization check blocks the command
  And   no chat is registered for notifications automatically

**Input table:**
| Field   | Type | Example   | Constraints          |
|---------|------|-----------|----------------------|
| user_id | int  | 987654321 | From Telegram update |
| chat_id | int  | 123456789 | From Telegram update |
| command | str  | `/whoami` | Must be `/whoami`    |

**Expected output / state change:**
| Assertion                                | How to verify                         |
|------------------------------------------|---------------------------------------|
| Response contains the exact user_id       | Inspect result.text                   |
| Response contains the exact chat_id       | Inspect result.text                   |
| Chat repository remains unchanged         | `list_chats()` is still empty         |

**Also test:**
- `/whoami` works even when allowed-users is empty
- `/whoami` works for unauthorized users

**Verify (Classical school, black-box):**
```python
fake_repo = InMemoryTelegramChatRepository()
use_case = HandleTelegramCommand(
    bot_manager=FakeBotManager(),
    chat_repo=fake_repo,
    strategy_dir=FakeStrategyDirectory([]),
    session_store=InMemoryTelegramSessionStore(),
    allowed_users=frozenset(),
)

result = await use_case.execute(TelegramCommandRequest(
    command="/whoami", args="", chat_id=123456789,
    user_id=987654321, message_id=1,
))

assert "987654321" in result.text
assert "123456789" in result.text
assert await fake_repo.list_chats() == []
```

---

### Scenario: User checks bot status when idle
**Priority:** Must
**Slice:** 1

**Telegram UI flow:**
```
User:  /status

Bot:   📊 *Bot Status*
       State: ⏸ Idle
       No bot running\.

       *Last Run:* r\_abc122
       Strategy: trend\_follow\.yaml
       Symbol: ETH\-USD / 4h
       Ended: 2026\-06\-15 14:30 UTC
       Signals: 23 | Fills: 5

       [Run new bot] [History]
```

**Gherkin:**
  Given no bot is currently running
  And   the repository has at least one completed BotRun
  When  the user sends `/status`
  Then  the bot responds with "Idle" state
  And   the response shows the most recent completed run summary
  And   the inline keyboard offers "Run new bot" and "History"

**Also test:**
- No prior runs at all → "No run history" instead of last run
- Bot is running → different format (see next scenario)
- Unauthorized user → "Unauthorized"

---

### Scenario: User checks bot status when running
**Priority:** Must
**Slice:** 1

**Telegram UI flow:**
```
User:  /status

Bot:   📊 *Bot Status*
       State: ▶ Running
       Run ID: r\_abc123
       Strategy: macd\_cross\.yaml
       Symbol: BTC\-USD / 1h
       Mode: LIVE
       Uptime: 2h 34m

       *Last Signal:* BUY @ 67,432\.50 \(2m ago\)
       Position: LONG 0\.05 BTC
       PnL: \+$124\.30

       *Totals:*
       Signals: 47 | Orders: 12 | Fills: 11

       [Refresh] [Stop Bot]
```

**Gherkin:**
  Given a bot is running with strategy macd_cross.yaml on BTC-USD/1h in LIVE mode
  When  the user sends `/status`
  Then  the bot responds with "Running" state
  And   the response shows strategy, symbol, interval, mode, uptime
  And   the response shows last signal, position, PnL, and cumulative counts
  And   the inline keyboard offers "Refresh" and "Stop Bot"

**Also test:**
- No position (flat) → "No open position"
- Stale data (last signal > 5 min) → show warning indicator
- PnL is negative → shown normally, not hidden

---

### Scenario: User starts a bot via guided inline-keyboard flow
**Priority:** Must
**Slice:** 1

**Telegram UI flow (full sequence):**
```
Step 1 — User triggers /run:
User:  /run

Bot:   *Start a Bot*
       Select a strategy:
       [macd_cross.yaml] [trend_follow.yaml] [breakout.yaml] [momentum.yaml]
       [▶ More...]

Step 2 — User taps a strategy:
User:  taps [macd_cross.yaml]

Bot:   Strategy: macd\_cross\.yaml
       Select symbol:
       [BTC] [ETH] [SOL] [ARB] [DOGE]
       [▶ More...]

Step 3 — User taps a symbol:
User:  taps [BTC]

Bot:   Strategy: macd\_cross\.yaml
       Symbol: BTC
       Select interval:
       [1m] [5m] [15m] [1h] [4h] [1d]

Step 4 — User taps an interval:
User:  taps [1h]

Bot:   Strategy: macd\_cross\.yaml
       Symbol: BTC / 1h
       Select mode:
       [📊 Dry Run] [🧪 Testnet] [⚠ Live]

Step 5a — User taps Dry Run:
User:  taps [📊 Dry Run]

Bot:   ✅ *Bot started\!*
       Run ID: r\_abc123
       Strategy: macd\_cross\.yaml
       Symbol: BTC\-USD / 1h
       Mode: DRY\_RUN

       No real orders will be placed\.
       Use /status to monitor or /stop to halt\.

       [Status] [Stop]

Step 5b — User taps Live (requires confirmation):
User:  taps [⚠ Live]

Bot:   ⚠️ *LIVE TRADING CONFIRMATION*
       Strategy: macd\_cross\.yaml
       Symbol: BTC\-USD / 1h
       Mode: LIVE

       This will place *real orders* on Hyperliquid with real funds\.
       Are you sure?

       [✅ Yes, start live trading] [❌ Cancel]

User:  taps [✅ Yes, start live trading]

Bot:   ✅ *Bot started\!*
       Run ID: r\_abc124
       Strategy: macd\_cross\.yaml
       Symbol: BTC\-USD / 1h
       Mode: LIVE

       Real orders WILL be placed\.
       Use /status to monitor or /stop to halt\.

       [Status] [Stop]
```

**Gherkin (happy path, dry_run):**
  Given the bot is not currently running
  And   the strategies directory contains at least two .yaml files
  When  the user sends `/run`
  Then  the bot responds with an inline keyboard listing available strategies
  When  the user selects a strategy via callback
  Then  the bot responds with an inline keyboard for symbol selection
  When  the user selects a symbol via callback
  Then  the bot responds with an inline keyboard for interval selection
  When  the user selects an interval via callback
  Then  the bot responds with an inline keyboard for mode selection
  When  the user selects "Dry Run"
  Then  the bot calls bot_manager.start() with the selected params and mode="dry_run"
  And   the bot responds with a success message including the bot_run_id

**Gherkin (live mode with confirmation):**
  Given the user has selected strategy, symbol, interval, and taps "Live"
  When  the confirmation prompt appears
  And   the user taps "✅ Yes, start live trading"
  Then  the bot calls bot_manager.start() with mode="live" and live_trading_ack=True
  And   the bot responds with a success message and a live-trading warning

**Gherkin (live mode cancelled):**
  Given the user has selected strategy, symbol, interval, and taps "Live"
  When  the confirmation prompt appears
  And   the user taps "❌ Cancel"
  Then  no bot is started
  And   the bot responds with "Start cancelled" or returns to mode selection

**Callback/session data format at each step:**

Callback data must be compact. Full flow state is stored in a server-side
`TelegramRunFlowSession` keyed by `(chat_id, message_id)` or a short
`session_id`. Callback data carries only action + short payload.

| Step          | callback_data format         | Example                 | Session update |
|---------------|------------------------------|-------------------------|----------------|
| Strategy      | `run:<sid>:strat:<index>`    | `run:a1:strat:0`        | `strategy_path` from current strategy page index |
| Symbol        | `run:<sid>:sym:<ticker>`     | `run:a1:sym:BTC`        | `symbol="BTC"` |
| Interval      | `run:<sid>:int:<interval>`   | `run:a1:int:1h`         | `interval="1h"` |
| Mode          | `run:<sid>:mode:<mode>`      | `run:a1:mode:dry_run`   | `mode="dry_run"` |
| Live confirm  | `run:<sid>:confirm:yes`      | `run:a1:confirm:yes`    | start live if env ack is also true |
| Live cancel   | `run:<sid>:confirm:no`       | `run:a1:confirm:no`     | cancel or return to mode selection |

**Also test:**
- Bot already running → "Bot already running. Stop it first." message
- Strategy directory empty → "No strategies found"
- Strategy file deleted between listing and selection → graceful error
- Invalid callback data (tampered, unknown session, expired session) → "Invalid selection, please start again with /run"
- Network error during bot_manager.start() → error message, not crash
- All modes: dry_run, testnet, live all work
- Live mode only starts when BOTH `FINBOT_LIVE_TRADING_ACK=true` and Telegram confirmation are present
- If >10 strategies, shows "More..." pagination button
- Callback data stays under Telegram's 64-byte limit

**Verify (Classical school, black-box) — happy path:**
```python
fake_manager = FakeBotManager()
fake_repo = InMemoryTelegramChatRepository()
fake_strategy_dir = FakeStrategyDirectory(["macd_cross.yaml", "trend_follow.yaml"])
fake_sessions = InMemoryTelegramSessionStore()

use_case = HandleTelegramCommand(
    bot_manager=fake_manager,
    chat_repo=fake_repo,
    strategy_dir=fake_strategy_dir,
    session_store=fake_sessions,
    allowed_users={987654321},
)

# Step 1: /run → show strategies
result = await use_case.execute(TelegramCommandRequest(
    command="/run", args="", chat_id=123456789, user_id=987654321,
))
assert len(result.reply_markup.inline_keyboard) >= 2

# Step 5a: select dry_run mode (callback with accumulated state)
session = fake_sessions.create(chat_id=123456789, message_id=100)
session.strategy_path = "macd_cross.yaml"
session.symbol = "BTC"
session.interval = "1h"
fake_sessions.save(session)

result = await use_case.handle_callback(CallbackQueryRequest(
    callback_data=f"run:{session.session_id}:mode:dry_run",
    chat_id=123456789, user_id=987654321, message_id=100,
    callback_query_id="cq_1",
))
assert fake_manager.start_called_with == {
    "strategy_path": "macd_cross.yaml",
    "symbol": "BTC", "interval": "1h", "mode": "dry_run",
}
assert "Bot started" in result.text
assert "r_" in result.text
```

---

### Scenario: User stops a running bot
**Priority:** Must
**Slice:** 1

**Telegram UI flow:**
```
User:  /stop

Bot:   ⏹ *Bot stopped\.*
       Run: r\_abc123 \(macd\_cross\.yaml / BTC\-USD\)
       Duration: 2h 34m
       Signals: 47 | Orders: 12 | Fills: 11
       PnL: \+$124\.30

       [View details] [Start new bot]
```

**Gherkin:**
  Given a bot is currently running with run_id r_abc123
  When  the user sends `/stop`
  Then  the bot calls bot_manager.stop()
  And   the bot responds with a summary of the stopped run
  And   the inline keyboard offers "View details" and "Start new bot"

**Also test:**
- No bot running → "No bot is currently running"
- Stop while bot is in error state → still stops cleanly
- Rapid double /stop → second returns "No bot running" (idempotent)

---

### Scenario: User gets help with /help
**Priority:** Must
**Slice:** 1

**Telegram UI flow:**
```
User:  /help

Bot:   *Finbot Commands*

       /run — Start a trading bot \(guided setup\)
       /stop — Stop the running bot
       /status — View bot status, position & stats
       /history — Browse past bot runs
       /panic — 🚨 Emergency: cancel orders \+ close position
       /help — Show this message

       *Safety:*
       • Default mode is Dry Run — no real orders
       • Live/Testnet require explicit confirmation
       • Only one bot can run at a time

       [Run Bot] [Status] [History]
```

**Gherkin:**
  Given the Telegram bot is running
  When  the user sends `/help`
  Then  the bot responds with a list of all commands and their descriptions
  And   the response includes safety notes about dry-run default and live confirmation

**Also test:**
- /help from unauthorized user → shows minimal help plus `/whoami` instructions; no control actions are exposed

---

### Scenario: Bot sends proactive trade notification
**Priority:** Must
**Slice:** 1

**Telegram UI flow:**
```
Bot:   🔔 *Trade Executed*
       BUY 0\.05 BTC\-USD @ $67,432\.50
       Order: \#12345 | Run: r\_abc123
       [View status]

Bot:   🔔 *Trade Executed*
       SELL 0\.05 BTC\-USD @ $67,890\.00
       PnL: \+$22\.87
       Order: \#12346 | Run: r\_abc123
       [View status]
```

**Gherkin:**
  Given a bot is running in any mode
  When  an order fill occurs
  Then  a notification is sent to all authorized chats with notifications enabled
  And   the notification includes side, size, symbol, price, and PnL (if closing)
  And   the notification includes an inline button to view status

**Also test:**
- Multiple authorized chats → all receive the notification
- No authorized chats registered → no error, notification silently dropped
- Fill for partial close → PnL shown
- Notification sent while user is in middle of /run flow → new message, doesn't interfere

---

### Scenario: Bot sends proactive risk notification
**Priority:** Must
**Slice:** 1

**Telegram UI flow:**
```
Bot:   ⚠️ *Risk Event*
       Daily loss limit reached: \-$25\.00
       *Bot stopped\.* No further orders will be placed\.
       Run: r\_abc123
       [View details]

Bot:   ⚠️ *Risk Event*
       Stale market data \(>120s\)\. Orders blocked\.
       Run: r\_abc123

Bot:   ❌ *Error*
       Exchange connection lost\. Retrying in 30s\.\.\.
       Run: r\_abc123
```

**Gherkin:**
  Given a bot is running
  When  a risk gate blocks an order or stops the bot
  Then  a notification is sent to all authorized chats
  And   the notification includes the risk event type and reason

**Also test:**
- Daily loss gate → bot stopped notification
- Stale data gate → orders blocked notification (bot continues)
- Duplicate signal gate → no notification (too noisy for actionable events only)

---

### Scenario: Unauthorized user is rejected
**Priority:** Must
**Slice:** 1

**Telegram UI flow:**
```
User (not in allowed list):  /start

Bot:   ⛔ *Unauthorized\.*
       You are not authorized to control this trading bot\.
       Contact the bot administrator to be added\.
```

**Gherkin:**
  Given the Telegram bot has a non-empty allowed-users list
  When  a user whose ID is NOT in the allowed list sends any control command
  Then  the bot responds with "Unauthorized"
  And   no bot manager operation is executed
  And   the chat ID is NOT persisted

**Gherkin (fail-closed setup):**
  Given Telegram is enabled
  And   `FINBOT_TELEGRAM_ALLOWED_USERS` is empty
  When  any user sends `/run`, `/stop`, `/status`, `/panic`, `/history`, or `/list`
  Then  the bot responds that Telegram control is not configured
  And   the response tells the user to run `/whoami` and configure `FINBOT_TELEGRAM_ALLOWED_USERS`
  And   no bot manager operation is executed

**Also test:**
- Control commands blocked: /start, /status, /run, /stop, /panic, /history, /list
- `/whoami` allowed for everyone
- User ID 0 or None → rejected for control commands
- Empty allowed-users list → fail closed, not allow-all

---

### Scenario: Unknown command gets helpful response
**Priority:** Must
**Slice:** 1

**Telegram UI flow:**
```
User:  /asdf

Bot:   Unknown command: /asdf
       Use /help to see available commands\.
```

**Gherkin:**
  Given the Telegram bot is running
  When  the user sends a command not in the registered command list
  Then  the bot responds with "Unknown command" and a hint to use /help

---

### Scenario: Bot already running — /run is rejected
**Priority:** Must
**Slice:** 1

**Telegram UI flow:**
```
User:  /run

Bot:   ⚠️ A bot is already running \(r\_abc123\)\.
       Stop it first with /stop, then start a new one\.
       [Stop current bot] [Cancel]
```

**Gherkin:**
  Given a bot is currently running
  When  the user sends `/run`
  Then  the bot responds that a bot is already running
  And   the inline keyboard offers "Stop current bot"

---

## Slice 1 test completeness matrix

Every Slice 1 scenario must have at least one black-box application test using
real DTOs and in-memory fakes. The junior developer should implement these test
names before writing production code:

| Scenario | Required test name | Primary assertion |
|----------|--------------------|-------------------|
| /start authorized | `test_start_registers_authorized_chat_and_returns_welcome` | Chat persisted and welcome keyboard returned |
| /whoami | `test_whoami_returns_user_and_chat_id_without_authorization` | Exact user_id/chat_id in response, no chat persisted |
| /status idle | `test_status_idle_returns_last_run_summary` | Idle text and last run fields shown |
| /status running | `test_status_running_returns_live_state_summary` | Running text, run id, symbol, counts shown |
| /run flow dry_run | `test_run_flow_starts_dry_run_after_keyboard_selection` | BotManager receives selected strategy/symbol/interval/mode |
| /run flow live | `test_run_flow_live_requires_env_ack_and_telegram_confirmation` | No start before confirmation; start only when both acks true |
| /stop | `test_stop_returns_stopped_summary` | BotManager stop result formatted; second stop is idempotent |
| /help | `test_help_lists_commands_and_safety_notes` | Commands and safety notes shown |
| trade notification | `test_trade_notification_broadcasts_to_all_registered_chats` | Fake Telegram outbox has one message per chat |
| risk notification | `test_risk_notification_broadcasts_actionable_risk_event` | Risk reason visible in every message |
| unauthorized | `test_unauthorized_user_cannot_execute_control_command` | No bot manager state change; no chat persisted |
| unknown command | `test_unknown_command_returns_help_hint` | Response contains `/help` |
| bot already running | `test_run_when_bot_running_returns_rejection_keyboard` | No second start; stop/cancel buttons present |

**Required fakes:**
- `FakeBotManager` — real stateful fake, no mocks; records observable started/stopped state
- `InMemoryTelegramChatRepository` — stores `TelegramChat` entities
- `InMemoryTelegramSessionStore` — stores short-lived run-flow sessions
- `FakeStrategyDirectory` — returns deterministic strategy file names
- `FakeTelegramOutbox` or `FakeTelegramBot` — stores sent messages as observable output

---

## Slice 2 — Should Have

---

### Scenario: User browses run history
**Priority:** Should
**Slice:** 2

**Telegram UI flow:**
```
User:  /history

Bot:   📋 *Recent Bot Runs* \(1–5 of 23\)

       1\. r\_abc123 — macd\_cross / BTC\-USD / 1h
       LIVE \| 2h 34m \| \+$124\.30

       2\. r\_abc122 — trend\_follow / ETH\-USD / 4h
       DRY\_RUN \| 1h 12m \| 23 signals

       3\. r\_abc121 — breakout / SOL\-USD / 15m
       DRY\_RUN \| 45m \| 8 signals

       [◀ Prev] [▶ Next] [Select run...]
```

**Gherkin:**
  Given the repository has 23 completed bot runs
  When  the user sends `/history`
  Then  the bot responds with a paginated list of the 5 most recent runs
  And   each entry shows run_id, strategy, symbol, interval, mode, duration, PnL/signals
  And   the inline keyboard offers "Prev", "Next", and "Select run..."

**Also test:**
- Fewer than 5 runs → no "Next" button
- Zero runs → "No runs yet. Start one with /run"

---

### Scenario: User views detailed run results
**Priority:** Should
**Slice:** 2

**Telegram UI flow:**
```
User:  taps [Select run...] → selects [r_abc123]

Bot:   📋 *Run r\_abc123*
       Strategy: macd\_cross\.yaml
       Symbol: BTC\-USD / 1h
       Mode: LIVE
       Started: 2026\-06\-16 10:00 UTC
       Ended: 2026\-06\-16 12:34 UTC

       *Results:*
       Signals: 47 | Orders: 12
       Fills: 11 | Risk Events: 2
       PnL: \+$124\.30

       [Show signals] [Show orders] [Show fills] [Back]
```

**Gherkin:**
  Given the user has selected a run from the history list
  When  the run details are requested
  Then  the bot responds with the run's full summary
  And   the inline keyboard offers to drill into signals, orders, or fills

---

### Scenario: User triggers emergency panic
**Priority:** Should
**Slice:** 2

**Telegram UI flow (bot running — symbol inferred from current run):**
```
User:  /panic

Bot:   🚨 *EMERGENCY — BTC\-USD*
       Select action:
       [Cancel all orders] [Close position] [Both] [❌ Cancel]

User:  taps [Both]

Bot:   ⚠️ *PANIC CONFIRMATION*
       This will:
       • Cancel all open orders for BTC\-USD
       • Market\-close any open BTC\-USD position
       Are you sure?
       [✅ Confirm panic] [❌ Cancel]

User:  taps [✅ Confirm panic]

Bot:   🚨 *PANIC executed:*
       • Orders cancelled: 3
       • Position closed: LONG 0\.05 BTC @ $67,430\.00
       Bot has been stopped\.
```

**Telegram UI flow (idle — user must select symbol first):**
```
User:  /panic

Bot:   🚨 *EMERGENCY*
       No bot is currently running, so select a symbol first:
       [BTC] [ETH] [SOL] [ARB] [DOGE]

User:  taps [BTC]

Bot:   🚨 *EMERGENCY — BTC\-USD*
       Select action:
       [Cancel all orders] [Close position] [Both] [❌ Cancel]
```

**Gherkin (running):**
  Given a bot is running with symbol BTC-USD, open orders, and a position
  When  the user sends `/panic`
  Then  the bot infers BTC-USD from the current run
  And   the bot responds with action options: cancel orders, close position, both, cancel
  When  the user selects "Both" and confirms
  Then  all open BTC-USD orders are cancelled and the BTC-USD position is market-closed
  And   the bot is stopped
  And   the response shows what was cancelled/closed

**Gherkin (idle):**
  Given no bot is running
  When  the user sends `/panic`
  Then  the bot first asks the user to select a symbol
  When  the user selects BTC and then confirms "Both"
  Then  all open BTC-USD orders are cancelled and the BTC-USD position is market-closed

**Also test:**
- No open orders → "Orders cancelled: 0"
- No open position → "No position to close"
- Panic bypasses all risk gates (kill switch is first-class)
- Exchange unreachable → error message, not crash
- Panic cannot execute without explicit inline confirmation

---

### Scenario: User lists available strategies
**Priority:** Should
**Slice:** 2

**Telegram UI flow:**
```
User:  /list

Bot:   📁 *Available Strategies* \(/strategies\)

       1\. macd\_cross\.yaml \(1\.2 KB\)
       2\. trend\_follow\.yaml \(2\.1 KB\)
       3\. breakout\.yaml \(1\.8 KB\)
       4\. momentum\.yaml \(3\.4 KB\)

       [Run a strategy]
```

**Gherkin:**
  Given the strategies directory contains 4 .yaml files
  When  the user sends `/list`
  Then  the bot responds with a list of strategy filenames and sizes
  And   the inline keyboard offers "Run a strategy"

**Also test:**
- Directory doesn't exist → "Strategies directory not found"
- Directory empty → "No strategy files found"
- Non-.yaml files in dir → ignored

---

## Slice 3 — Could Have

---

### Scenario: User mutes/unmutes notifications
**Priority:** Could
**Slice:** 3

**Gherkin:**
  Given the user is authorized
  When  the user sends `/mute`
  Then  notifications are suppressed for this chat
  And   the bot confirms "Notifications muted. Use /unmute to resume."

  When  the user sends `/unmute`
  Then  notifications resume for this chat

---

### Scenario: User filters notifications by type
**Priority:** Could
**Slice:** 3

**Gherkin:**
  Given the user is authorized
  When  the user sends `/notify trades_only`
  Then  only trade execution notifications are sent to this chat
  And   risk events and errors are suppressed

---

### Scenario: User enters custom symbol in /run flow
**Priority:** Could
**Slice:** 3

**Telegram UI flow:**
```
User:  taps [Custom...] on symbol selection

Bot:   Enter the ticker symbol \(e\.g\., BTC, ETH, SOL\):

User:  types "DOGE"

Bot:   Strategy: macd\_cross\.yaml
       Symbol: DOGE
       Select interval:
       [1m] [5m] [15m] [1h] [4h] [1d]
```

**Gherkin:**
  Given the user is in the symbol selection step of /run
  When  the user taps "Custom..."
  Then  the bot prompts for a text input
  When  the user types a valid ticker
  Then  the flow continues to interval selection with that symbol

**Also test:**
- Empty symbol → "Symbol cannot be empty. Try again."
- Symbol with special characters → rejected
