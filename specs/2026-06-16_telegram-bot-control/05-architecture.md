# Architecture Decisions — Telegram Bot Control

---

## ADR-1: Use `python-telegram-bot` with polling, NOT webhooks

**Context:** Telegram offers two update delivery mechanisms: long-polling
(`getUpdates`) and webhooks (HTTP POST to a public URL). Webhooks are more
efficient for high-volume bots but require a public HTTPS endpoint and TLS
certificate management.

**Decision:** Use long-polling via `python-telegram-bot`'s `Application.updater`.

**Consequences:**
- **Easier:** No public endpoint needed. Finbot can run behind NAT/firewall.
- **Easier:** No TLS certificate management. No webhook secret verification.
- **Easier:** Proven in telegrammy project with the same PTB version.
- **Harder:** Slightly higher latency (poll interval, PTB default ~1s).
  Acceptable for a trading control surface where commands are infrequent
  and human-initiated.
- **Harder:** PTB's `Application` owns its own asyncio tasks. Must coexist
  with MCP server's event loop. Mitigated: PTB v21 is async-native.

---

## ADR-2: Telegram bot runs in-process with MCP server, on its own asyncio loop/thread

**Context:** Finbot already has an MCP server running as a long-lived process.
Telegram integration could run as a separate process (microservice) or in the
same process. `startup/mcp.py:create_server()` may run before an asyncio event
loop exists, so blindly calling `asyncio.create_task()` is unsafe.

**Decision:** Run in the same process, sharing the `BotManager` instance, but run
Telegram polling on a dedicated daemon thread with its own asyncio event loop
owned by `TelegramControlPlane`.

**Consequences:**
- **Easier:** No IPC needed. Both MCP and Telegram share the same `BotManager`
  singleton — state is consistent across both control surfaces.
- **Easier:** Single deployment. One `run_mcp.py` starts everything.
- **Safer:** Does not depend on FastMCP's event-loop lifecycle.
- **Harder:** Cross-thread notifications require a thread-safe dispatcher.
  Mitigated with `asyncio.run_coroutine_threadsafe()`.
- **Harder:** If the MCP server is restarted, the Telegram bot also restarts.
  Acceptable — both are stateless at the transport layer (state is in SQLite).

---

## ADR-3: Inline keyboard browsing, not free-text input

**Context:** Telegram commands can accept arguments as free text
(`/run macd_cross.yaml BTC 1h`) or guide the user through inline keyboards.

**Decision:** Use inline keyboards for all multi-step flows. Free-text commands
are accepted as shortcuts but the primary UX is keyboard-driven.

**Consequences:**
- **Easier:** No parsing/validation of free-text arguments. No ambiguity about
  valid strategy names, symbols, or intervals.
- **Easier:** Discovery — users see available options rather than needing to
  know exact filenames.
- **Easier:** Mobile-friendly — tapping buttons is faster than typing on a phone.
- **Harder:** More code. Each step requires callback handling and state management.
- **Harder:** Callback data has a 64-byte limit on Telegram. Accumulated state
  (strategy + symbol + interval) must fit. Mitigated with a server-side
  `TelegramRunFlowSession` keyed by short callback payloads such as
  `run:a1:strat:0`.

---

## ADR-4: Broadcast notifications to all authorized chats by default

**Context:** When a trade is executed or a risk event fires, notifications should
go to all authorized Telegram chats.

**Decision:** Broadcast by default. No per-chat subscription management in MVP.

**Consequences:**
- **Easier:** Simple implementation — iterate `chat_repo.list_chats()`, send to each.
- **Easier:** All authorized users see all events. No confusion about "why didn't
  I get notified?"
- **Harder:** Noisy for users who only want certain event types. Mitigation:
  `/mute` and `/unmute` commands in Slice 3; per-event-type filters in future.
- **Acceptable:** Trading bots generate relatively few events (not a high-frequency
  notification stream).

---

## ADR-5: Domain events use frozen dataclasses + synchronous notification port, not an event bus

**Context:** The bot needs to send notifications in response to domain events
(trade fills, risk triggers, errors). Runtime/account handling currently executes
synchronously in a background thread, while Telegram sending is async.

**Decision:** Use frozen dataclass events plus a synchronous `BotNotificationSender`
interface. The concrete Telegram implementation is a thread-safe dispatcher that
schedules async sends onto the Telegram loop using `asyncio.run_coroutine_threadsafe()`.
No general event bus is introduced.

**Consequences:**
- **Easier:** No event bus infrastructure. No subscription management.
- **Easier:** Runtime code does not need to know about asyncio.
- **Easier:** Call stack is explicit — easy to trace and debug.
- **Harder:** If scheduling fails, notification delivery can be missed. This is
  acceptable because SQLite remains the canonical record.

---

## ADR-6: Telegram-specific code stays in presentation + infrastructure

**Context:** Where does Telegram formatting, MarkdownV2 escaping, and inline
keyboard construction live?

**Decision:**
- `infrastructure/adapters/python_telegram_bot_adapter.py` — PTB library wrapper,
  error classification. No formatting logic.
- `presentation/telegram/bot_handler.py` — PTB `Application` setup, command/callback
  routing. Converts PTB types → DTOs → use case → DTOs → PTB types. No domain logic.
- `presentation/telegram/notification_sender.py` — MarkdownV2 escaping, inline
  keyboard construction, event-to-message formatting. Implements domain interface
  `BotNotificationSender`.

**Consequences:**
- **Easier:** Application use cases (`HandleTelegramCommand`) are presentation-
  agnostic. They return `TelegramCommandResult` DTOs with `text` and `reply_markup`
  as generic dicts. The presentation layer converts dicts to PTB types.
- **Easier:** If we switch to a different Telegram library or add another chat
  platform, only the presentation layer changes.
- **Verifiable:** `HandleTelegramCommand` can be tested with fake `TelegramBotPort`
  that just captures the result DTOs — no PTB dependency in tests.

---

## ADR-7: No durable message queue or outbox pattern for notifications

**Context:** If the Telegram API is temporarily unavailable, trade notifications
could be lost. An outbox pattern (persist notification, send, mark sent) would
prevent loss.

**Decision:** Fire-and-forget. No persistence, no retry queue for notifications.

**Consequences:**
- **Easier:** Dramatically simpler implementation.
- **Acceptable:** Trade notifications are informational. The canonical record is
  in the SQLite database (signals, orders, fills). Users can always query history.
- **Acceptable:** Risk events that stop the bot are critical, but the bot stop is
  persisted regardless of notification delivery.
- **Risk:** If Telegram is down for an extended period, users miss real-time
  notifications. Mitigation: They can use `/status` to check state manually.
- **Note:** The in-memory cross-thread dispatcher queue is allowed; the decision
  only rejects a durable database outbox/retry system.

---

## ADR-8: Strategy files read from local filesystem, not uploaded

**Context:** Users could upload strategy YAML files via Telegram's document
sharing, avoiding the need to SSH into the server.

**Decision:** Strategies must already exist on the filesystem. No upload support.

**Consequences:**
- **Easier:** No file handling, size limits, virus scanning, or overwrite concerns.
- **Easier:** Strategy files require validation before use — validation is already
  handled by the existing `ValidateStrategyUseCase` when loading from filesystem.
- **Harder:** Users must have filesystem access to add strategies. Acceptable for
  initial release — strategies are typically authored offline in Finbar and
  deployed intentionally, not ad-hoc from a phone.

---

## ADR-9: MarkdownV2 for all bot responses

**Context:** Telegram supports HTML and MarkdownV2 for message formatting.

**Decision:** Use MarkdownV2 exclusively. No HTML formatting.

**Consequences:**
- **Easier:** Single formatting path. Consistent across all responses.
- **Easier:** MarkdownV2 supports bold, italic, code, links — everything we need.
- **Harder:** Requires escaping special characters. `_ * [ ] ( ) ~ ` > # + - = | { } . !`
  must be escaped with `\`. Centralized in `_escape_mdv2()` helper.
- **Harder:** Numbers with decimal points (e.g., `$67,432.50`) don't need escaping
  since the dot is not adjacent to digits in a way that triggers MarkdownV2 list
  detection. Still safe to escape liberally.

---

## ADR-10: Telegram authorization fails closed

**Context:** Telegram bots are reachable by anyone who knows or discovers the bot
username. A misconfigured allow-list could expose trading controls.

**Decision:** When `FINBOT_TELEGRAM_ENABLED=true`, control commands are allowed
only for IDs in `FINBOT_TELEGRAM_ALLOWED_USERS`. If the allow-list is empty,
control commands are denied. `/whoami` is the only command available to everyone
so the operator can discover the Telegram user ID to add to configuration.

**Consequences:**
- **Safer:** A missing environment variable cannot accidentally expose trading
  controls to the world.
- **Slightly harder:** First setup requires `/whoami` then editing `.env`.
- **Clear:** Junior developers should not implement an "empty means everyone"
  shortcut.

---

## ADR-11: Database schema does not need backward compatibility during development

**Context:** Finbot has not been released. Existing SQLite files are developer
artifacts, not production customer data.

**Decision:** Telegram schema changes do not need backward-compatible migrations
for old dev databases. Tests should validate the final schema on fresh databases.
Existing dev databases may be deleted/rebuilt when schema changes.

**Consequences:**
- **Easier:** The `telegram_chats` table can be added directly to the current
  migration set without maintaining multiple historical upgrade paths.
- **Faster:** Junior developers can focus on the final correct schema.
- **Caveat:** Once Finbot is released or real trading data must be preserved,
  this decision must be revisited and replaced with normal forward-only migrations.
