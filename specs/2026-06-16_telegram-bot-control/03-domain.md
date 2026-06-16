# Domain Model — Telegram Bot Control

## Entities

| Entity | Fields | Behaviour | Persisted? |
|--------|--------|-----------|------------|
| `TelegramConfig` | `bot_token: SecretStr`, `allowed_user_ids: frozenset[int]`, `enabled: bool`, `strategies_dir: str`, `default_symbols: list[str]` | Validates token is non-empty when enabled; authorization fails closed when `allowed_user_ids` is empty; `/whoami` remains allowed | No (read from env) |
| `TelegramCommand` | `command: str`, `args: str`, `chat_id: int`, `user_id: int`, `message_id: int`, `timestamp: datetime` | Immutable value object representing a parsed command | No (transient) |
| `CallbackQuery` | `callback_data: str`, `chat_id: int`, `user_id: int`, `message_id: int`, `callback_query_id: str` | Immutable parsed callback request; full state is loaded from session store | No (transient) |
| `TelegramRunFlowSession` | `session_id: str`, `chat_id: int`, `message_id: int`, `strategy_path: str | None`, `symbol: str | None`, `interval: str | None`, `mode: str | None`, `created_at: datetime`, `expires_at: datetime` | Stores `/run` flow state so callback_data stays under 64 bytes | No (in-memory, short-lived) |
| `TelegramChat` | `chat_id: int`, `user_id: int`, `registered_at: datetime`, `notifications_enabled: bool` | Represents an authorized chat subscribed to notifications | Yes (SQLite) |
| `SendResult` | `success: bool`, `message_id: int | None`, `error: str | None`, `transient: bool` | Return value for Telegram send operations | No |

## Value Objects

| Name | Fields | Used where |
|------|--------|------------|
| `ChatId` | `value: int` | Type-safe wrapper for Telegram chat IDs |
| `UserId` | `value: int` | Type-safe wrapper for Telegram user IDs |
| `CommandName` | `value: str` | Enumeration: /start, /stop, /status, /run, /history, /panic, /help, /list |
| `CallbackAction` | `action: str, payload: str` | Parsed callback_data: e.g., `strat:macd_cross.yaml` → action="strat", payload="macd_cross.yaml" |
| `BotRunSummary` | `run_id, strategy_name, symbol, interval, mode, started_at, ended_at, signal_count, order_count, fill_count, pnl` | DTO for /status and /history display; computed from BotManager state |

## Domain Events

| Event | Payload | Raised by |
|-------|---------|-----------|
| `TradeExecuted` | `run_id, symbol, side, size, price, pnl, order_id` | `LiveTradingRuntime` after fill is processed |
| `RiskEventTriggered` | `run_id, event_type, reason, bot_stopped: bool` | Risk gates including `DailyLossGate`, `StaleDataGate`, `MaxPositionGate`, `MaxOpenOrdersGate`, and `ModeGate` |
| `BotError` | `run_id, error_type, message` | `LiveTradingRuntime` on unrecoverable errors |
| `BotStarted` | `run_id, strategy_name, symbol, interval, mode` | `BotManager` after successful start |
| `BotStopped` | `run_id, reason, duration_seconds, signal_count` | `BotManager` after stop completes |

## Interfaces (for DI)

| Interface | Methods | Implemented by |
|-----------|---------|----------------|
| `TelegramBotPort` | `send_message(chat_id, text, parse_mode, reply_markup) → SendResult`, `edit_message_text(chat_id, message_id, text, parse_mode, reply_markup) → SendResult`, `answer_callback_query(callback_id, text) → bool`, `edit_message_reply_markup(chat_id, message_id, reply_markup) → bool` | `PythonTelegramBotAdapter` (real), `FakeTelegramBot` (tests) |
| `BotNotificationSender` | Synchronous facade: `notify_trade(event: TradeExecuted) → None`, `notify_risk(event: RiskEventTriggered) → None`, `notify_error(event: BotErrorEvent) → None` | `ThreadSafeTelegramNotificationDispatcher` (queues work onto Telegram loop) |
| `TelegramChatRepository` | `add_chat(chat) → None`, `get_chat(chat_id) → TelegramChat \| None`, `list_chats() → list[TelegramChat]`, `remove_chat(chat_id) → None`, `set_notifications(chat_id, enabled) → None` | `SqliteTelegramChatRepository` (real), `InMemoryTelegramChatRepository` (tests) |
| `TelegramSessionStore` | `create(chat_id, message_id) → TelegramRunFlowSession`, `get(session_id) → TelegramRunFlowSession | None`, `save(session) → None`, `delete(session_id) → None`, `expire_old(now) → int` | `InMemoryTelegramSessionStore` |
| `StrategyDirectory` | `list_strategies() → list[str]`, `strategy_exists(name) → bool`, `get_strategy_path(name) → str` | `FilesystemStrategyDirectory` (real), `FakeStrategyDirectory` (tests) |

## Required file layout (one class per file)

| Class | File |
|-------|------|
| `TelegramChat` | `finbot/core/domain/entities/telegram_chat.py` |
| `TelegramConfig` | `finbot/core/domain/entities/telegram_config.py` |
| `TelegramCommand` | `finbot/core/domain/entities/telegram_command.py` |
| `CallbackQuery` | `finbot/core/domain/entities/callback_query.py` |
| `TelegramRunFlowSession` | `finbot/core/domain/entities/telegram_run_flow_session.py` |
| `SendResult` | `finbot/core/domain/entities/send_result.py` |
| `TradeExecuted` | `finbot/core/domain/events/trade_executed.py` |
| `RiskEventTriggered` | `finbot/core/domain/events/risk_event_triggered.py` |
| `BotErrorEvent` | `finbot/core/domain/events/bot_error_event.py` |
| `TelegramCommandRequest` | `finbot/core/application/dto/telegram_command_request.py` |
| `TelegramCommandResult` | `finbot/core/application/dto/telegram_command_result.py` |
| `CallbackQueryRequest` | `finbot/core/application/dto/callback_query_request.py` |

## Entity vs ORM Separation

- **Domain entity:** `finbot.core.domain.entities.telegram_chat.py` — pure dataclass, no framework deps
- **Persistence table:** `telegram_chats` in SQLite. No ORM class is required because Finbot uses raw `sqlite3` repositories.
- **Mapper:** `finbot.infrastructure.repositories.sqlite_telegram_chat_repository.py` — `_to_domain()` / `_to_row()` methods within the repository class
- **Backward compatibility:** not required while Finbot is unreleased/dev-only. The SQLite schema may be rebuilt or existing dev tables may be replaced if that keeps implementation simpler and tests deterministic.

## Callback State Machine (for /run guided flow)

The multi-step `/run` flow uses callback_data with encoded state to track progress:

```
State: IDLE
  │  /run
  ▼
State: SELECTING_STRATEGY
  │  callback: strat:<filename>
  ▼
State: SELECTING_SYMBOL      (state carries strategy)
  │  callback: sym:<ticker>
  ▼
State: SELECTING_INTERVAL    (state carries strategy + symbol)
  │  callback: int:<interval>
  ▼
State: SELECTING_MODE        (state carries strategy + symbol + interval)
  │  callback: mode:<mode>
  ├── mode=dry_run ──────────► DONE (start bot)
  ├── mode=testnet ──────────► DONE (start bot with ack)
  └── mode=live ─────────────► SELECTING_LIVE_CONFIRM
        │  callback: live_confirm:yes → DONE (start bot with ack)
        └── callback: live_confirm:no  → SELECTING_MODE (back)
```

Callback data is compact and references a server-side session, e.g.:
```
run:a1:strat:0
run:a1:sym:BTC
run:a1:int:1h
run:a1:mode:live
run:a1:confirm:yes
```

`a1` is a short `session_id`. Full values such as selected strategy path are stored
in `TelegramRunFlowSession`. Each callback edits the original message with
`edit_message_text(...)` to show progress (strategy → "Strategy: macd_cross.yaml
Select symbol:"), avoiding message spam in the chat.
