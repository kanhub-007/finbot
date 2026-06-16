# Implementation Guide — Telegram Bot Control

Implementation follows Clean Architecture layers, bottom-up: domain → application
→ infrastructure → presentation → startup. Each step targets one or two files and
can be tested independently. Follow TDD: write the test first, see it fail, then
implement.

---

## Step 1: Add `python-telegram-bot` dependency

**File:** `pyproject.toml`

Add `"python-telegram-bot>=21.0"` to the `dependencies` list.

**Verify:** `python -m pip install -e "."` succeeds and `import telegram` works.

**Common mistake:** Installing PTB v20.x (pre-async). We need v21+ for native
`async/await` support matching the rest of Finbot's async infrastructure.

---

## Step 2: Define domain entities

### Step 2a: `TelegramChat` entity

**File:** `finbot/core/domain/entities/telegram_chat.py`

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class TelegramChat:
    chat_id: int
    user_id: int
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notifications_enabled: bool = True
```

Pure dataclass — no framework dependencies.

**Verify:** Instantiate in a Python shell; confirm frozen prevents mutation.

### Step 2b: `TelegramConfig` entity

**File:** `finbot/core/domain/entities/telegram_config.py`

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    allowed_user_ids: frozenset[int]
    enabled: bool = True
    strategies_dir: str = "strategies"
    default_symbols: tuple[str, ...] = ("BTC", "ETH", "SOL", "ARB", "DOGE")

    def __post_init__(self) -> None:
        if self.enabled and not self.bot_token:
            raise ValueError("bot_token is required when Telegram is enabled")
```

**Verify:** `TelegramConfig(bot_token="", enabled=True)` raises ValueError.

---

## Step 3: Define domain interfaces

### Step 3a: `SendResult` entity and `TelegramBotPort`

**Files:**
- `finbot/core/domain/entities/send_result.py`
- `finbot/core/domain/interfaces/telegram_bot_port.py`

Narrow interface — only the send/edit operations Finbot needs. We do NOT need
`get_updates()` because `python-telegram-bot`'s `Application` handles polling
inside the presentation layer.

`SendResult` must be in its own file to respect the one-class-per-file rule.

```python
# finbot/core/domain/entities/send_result.py
from dataclasses import dataclass


@dataclass(frozen=True)
class SendResult:
    """Result of attempting to send or edit a Telegram message."""

    success: bool
    message_id: int | None = None
    error: str | None = None
    transient: bool = False
```

```python
# finbot/core/domain/interfaces/telegram_bot_port.py
from abc import ABC, abstractmethod

from finbot.core.domain.entities.send_result import SendResult


class TelegramBotPort(ABC):
    """Port for Telegram send/edit operations."""

    @abstractmethod
    async def send_message(
        self, chat_id: int, text: str,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
    ) -> SendResult: ...

    @abstractmethod
    async def edit_message_text(
        self, chat_id: int, message_id: int, text: str,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
    ) -> SendResult: ...

    @abstractmethod
    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None,
    ) -> bool: ...

    @abstractmethod
    async def edit_message_reply_markup(
        self, chat_id: int, message_id: int,
        reply_markup: dict | None = None,
    ) -> bool: ...
```

**Verify:** Interface compiles; no imports from infrastructure.

### Step 3b: `TelegramChatRepository`

**File:** `finbot/core/domain/interfaces/telegram_chat_repository.py`

```python
from abc import ABC, abstractmethod
from finbot.core.domain.entities.telegram_chat import TelegramChat


class TelegramChatRepository(ABC):
    @abstractmethod
    async def add_chat(self, chat: TelegramChat) -> None: ...
    @abstractmethod
    async def get_chat(self, chat_id: int) -> TelegramChat | None: ...
    @abstractmethod
    async def list_chats(self) -> list[TelegramChat]: ...
    @abstractmethod
    async def remove_chat(self, chat_id: int) -> None: ...
```

### Step 3c: `BotNotificationSender`

**File:** `finbot/core/domain/interfaces/bot_notification_sender.py`

This interface is synchronous because the existing runtime and account event
handler run in a background thread. Implementations may enqueue work onto the
Telegram asyncio loop internally.

```python
from abc import ABC, abstractmethod

from finbot.core.domain.events.bot_error_event import BotErrorEvent
from finbot.core.domain.events.risk_event_triggered import RiskEventTriggered
from finbot.core.domain.events.trade_executed import TradeExecuted


class BotNotificationSender(ABC):
    """Thread-safe notification port used by runtime code."""

    @abstractmethod
    def notify_trade(self, event: TradeExecuted) -> None: ...
    @abstractmethod
    def notify_risk(self, event: RiskEventTriggered) -> None: ...
    @abstractmethod
    def notify_error(self, event: BotErrorEvent) -> None: ...
```

### Step 3d: `StrategyDirectory`

**File:** `finbot/core/domain/interfaces/strategy_directory.py`

```python
from abc import ABC, abstractmethod


class StrategyDirectory(ABC):
    @abstractmethod
    def list_strategies(self) -> list[str]: ...
    @abstractmethod
    def strategy_exists(self, name: str) -> bool: ...
    @abstractmethod
    def get_strategy_path(self, name: str) -> str: ...
```

---

## Step 4: Define domain events

One class per file:

| Class | File |
|-------|------|
| `TradeExecuted` | `finbot/core/domain/events/trade_executed.py` |
| `RiskEventTriggered` | `finbot/core/domain/events/risk_event_triggered.py` |
| `BotErrorEvent` | `finbot/core/domain/events/bot_error_event.py` |

Example:

```python
# finbot/core/domain/events/trade_executed.py
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TradeExecuted:
    """Domain event raised when a fill has been persisted."""

    run_id: str
    symbol: str
    side: str
    size: str
    price: str
    pnl: str | None
    order_id: str
    timestamp: datetime
```

**Verify:** Pure dataclasses; instantiable without any dependencies.

---

## Step 5: Define application DTOs

### Step 5a: Command request/result DTOs

**Files:**
- `finbot/core/application/dto/telegram_command_request.py`
- `finbot/core/application/dto/telegram_command_result.py`

```python
# telegram_command_request.py
from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramCommandRequest:
    """Request DTO for a Telegram slash command."""

    command: str
    args: str
    chat_id: int
    user_id: int
    message_id: int
```

```python
# telegram_command_result.py
from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramCommandResult:
    """Response DTO that presentation/telegram sends or edits."""

    text: str
    parse_mode: str = "MarkdownV2"
    reply_markup: dict | None = None
    edit_message_id: int | None = None
```

The use case returns this DTO. It must not call `TelegramBotPort` directly.

### Step 5b: Callback query request

**File:** `finbot/core/application/dto/callback_query_request.py`

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CallbackQueryRequest:
    callback_data: str
    chat_id: int
    user_id: int
    message_id: int
    callback_query_id: str
    state: dict = field(default_factory=dict)
```

---

## Step 6: Implement `HandleTelegramCommand` use case

**File:** `finbot/core/application/use_cases/handle_telegram_command.py`

Central use case. Routes commands to BotManager methods. For `/run`, manages
multi-step callback flow state. Formats all responses as `TelegramCommandResult`.
It does not send Telegram messages directly.

**Internal methods:**
- `execute(request) → TelegramCommandResult` — `/whoami`, authorization check + routing
- `handle_callback(request) → TelegramCommandResult` — callback state machine
- `_handle_whoami(request)` — always allowed; returns user_id/chat_id
- `_authorize(request)` — fail-closed authorization for all control commands
- `_handle_start(request)` — register authorized chat, return welcome
- `_handle_status(request)` — delegate to BotManager, format response
- `_handle_run_start(request)` — create session and list strategies
- `_handle_stop(request)` — delegate to BotManager.stop()
- `_handle_history(request)` — delegate to BotManager.list_bot_runs()
- `_handle_panic(request)` — if running infer symbol, otherwise ask symbol first
- `_handle_help(request)` — return command list
- `_handle_list(request)` — list strategy files

**Dependencies (all constructor-injected):**
- `bot_manager: BotManager`
- `chat_repo: TelegramChatRepository`
- `strategy_dir: StrategyDirectory`
- `session_store: TelegramSessionStore`
- `allowed_users: frozenset[int]`
- `live_trading_ack: bool` from settings (environment-level ack)

**Verify:** Unit test each handler method with fake dependencies.

**Size constraint:** If >300 lines, extract callback state machine into
`_run_flow_state_machine.py` helper.

---

## Step 7: Implement `SendBotNotification` application service

**File:** `finbot/core/application/use_cases/send_bot_notification.py`

Formats domain events into human-readable message DTOs and sends to all registered
chats via `TelegramBotPort`. This class is async and runs on the Telegram event
loop. Runtime code should not call it directly from the trading thread; it is
called by the thread-safe dispatcher in Step 13.

Dependencies:
- `bot_port: TelegramBotPort`
- `chat_repo: TelegramChatRepository`

**Verify:** Unit test with fake bot_port and fake chat_repo.

---

## Step 8: Implement `PythonTelegramBotAdapter`

**File:** `finbot/infrastructure/adapters/python_telegram_bot_adapter.py`

Wraps `telegram.Bot` from `python-telegram-bot`. Implements `TelegramBotPort`.

Key patterns (from telegrammy's adapter):
- Classify `TelegramError` subclasses as transient vs permanent
- `send_message()` and `edit_message_text()` catch `TelegramError` and return
  `SendResult` with `transient` flag — never raise
- `answer_callback_query()` returns bool (best-effort)
- Bot instance from env token; can accept pre-built `telegram.Bot` for testing

```python
class PythonTelegramBotAdapter(TelegramBotPort):
    def __init__(self, bot_token: str | None = None, *, bot: Bot | None = None):
        if bot is not None:
            self._bot = bot
        elif bot_token:
            self._bot = Bot(token=bot_token)
        else:
            raise ValueError("bot_token is required")
```

**Verify:** Unit test with a fake `telegram.Bot`. Test error classification.

**Common mistake:** Importing PTB types in domain interface. Adapter converts
PTB types → domain types internally; no PTB types leak upward.

---

## Step 9: Implement `SqliteTelegramChatRepository` and schema update

**Files:**
- `finbot/infrastructure/repositories/sqlite_telegram_chat_repository.py`
- `finbot/infrastructure/repositories/sqlite_migrator.py` (MODIFIED)

Add a `telegram_chats` table:

```sql
CREATE TABLE telegram_chats (
    chat_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    registered_at TEXT NOT NULL,
    notifications_enabled INTEGER NOT NULL DEFAULT 1
);
```

Mapper methods: `_to_domain(row) → TelegramChat`, `_to_row(chat) → dict`.

**Dev-phase schema note:** Finbot has not been released. Backward compatibility
is not required. It is acceptable to rebuild dev databases or replace existing
migration SQL if that keeps the schema simple. Tests must create a fresh database
and assert the final schema, not old-version upgrade behavior.

**Verify:** Test with in-memory SQLite database and a fresh temp-file database.
Confirm `sqlite_migrator.py` creates `telegram_chats`.

**Common mistake:** Using ORM patterns. Finbot uses raw `sqlite3` — do not
introduce SQLAlchemy for this table.

---

## Step 10: Implement `FilesystemStrategyDirectory`

**File:** `finbot/infrastructure/adapters/filesystem_strategy_directory.py`

Implements `StrategyDirectory`. Lists `.yaml` and `.yml` files from a directory.

```python
class FilesystemStrategyDirectory(StrategyDirectory):
    def __init__(self, directory: str):
        self._dir = Path(directory)

    def list_strategies(self) -> list[str]:
        if not self._dir.exists():
            return []
        return sorted(
            f.name for f in self._dir.iterdir()
            if f.suffix in (".yaml", ".yml")
        )
```

**Verify:** Unit test with temp directory containing .yaml files.

---

## Step 11: Wire `BotNotificationSender` into runtime/account handling

**Files:**
- `finbot/core/application/use_cases/account_event_handler.py` (MODIFIED)
- `finbot/core/application/use_cases/live_trading_runtime.py` (MODIFIED for risk/error events if needed)
- `finbot/startup/service_factory.py` (MODIFIED)

Fills are processed in `AccountEventHandler`, not primarily in
`LiveTradingRuntimeUseCase`, so trade notifications must be wired there.

Add optional `notification_sender: BotNotificationSender | None` constructor
parameter to `AccountEventHandler`. After a new fill is persisted and applied to
the trade ledger, call the synchronous notifier:

```python
if self._notification_sender is not None:
    self._notification_sender.notify_trade(TradeExecuted(...))
```

For risk events generated in the candle/order-planning pipeline, call
`notify_risk(...)` after the risk event has been persisted. For unrecoverable
runtime errors, call `notify_error(...)` before the runtime exits when possible.

**Important:** Do not `await` here. This code runs in the bot runtime thread.
The concrete notifier queues work onto the Telegram loop.

**Verify:** Existing tests pass; new tests with fake notifier confirm that new
fills/risk events enqueue notifications exactly once by observable state.

---

## Step 12: Build the Telegram bot handler (presentation layer)

**File:** `finbot/presentation/telegram/bot_handler.py`

Constructs PTB `Application`, registers `CommandHandler` and `CallbackQueryHandler`.
Converts PTB types → DTOs → use case → DTOs → PTB send/reply calls. Zero domain logic.

```python
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

class TelegramBotHandler:
    def __init__(self, bot_token: str, command_use_case: HandleTelegramCommand):
        self._app = Application.builder().token(bot_token).build()
        self._use_case = command_use_case
        for cmd in ["start", "whoami", "stop", "status", "run", "history", "panic", "help", "list"]:
            self._app.add_handler(CommandHandler(cmd, self._handle_command))
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

    async def start_polling(self) -> None:
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
```

**Verify:** Integration test with PTB's test utilities.

---

## Step 13: Build notification sender + thread-safe dispatcher

**Files:**
- `finbot/presentation/telegram/notification_sender.py`
- `finbot/infrastructure/adapters/thread_safe_telegram_notification_dispatcher.py`

`TelegramNotificationSender` is async and formats/sends messages on the Telegram
asyncio loop. `ThreadSafeTelegramNotificationDispatcher` implements the synchronous
`BotNotificationSender` interface used by runtime threads and schedules coroutines
onto the Telegram loop with `asyncio.run_coroutine_threadsafe()`.

```python
class ThreadSafeTelegramNotificationDispatcher(BotNotificationSender):
    def __init__(self, loop: asyncio.AbstractEventLoop, sender: TelegramNotificationSender):
        self._loop = loop
        self._sender = sender

    def notify_trade(self, event: TradeExecuted) -> None:
        asyncio.run_coroutine_threadsafe(self._sender.notify_trade(event), self._loop)
```

MarkdownV2 escaping belongs in `TelegramNotificationSender`. Characters needing
escape: `_ * [ ] ( ) ~ ` > # + - = | { } . !`

**Verify:** Unit test escaping; test dispatcher schedules onto a real test loop;
test muted chats don't receive notifications.

---

## Step 14: Add Telegram settings to config

**File:** `finbot/config/settings.py` (MODIFIED)

```python
telegram_bot_token: SecretStr = Field(default=SecretStr(""))
telegram_allowed_users: str = Field(default="")
telegram_enabled: bool = Field(default=False)
telegram_strategies_dir: str = Field(default="strategies")

@property
def telegram_allowed_user_ids(self) -> frozenset[int]:
    if not self.telegram_allowed_users.strip():
        return frozenset()
    return frozenset(
        int(uid.strip())
        for uid in self.telegram_allowed_users.split(",")
        if uid.strip()
    )

@property
def telegram_control_configured(self) -> bool:
    return bool(self.telegram_allowed_user_ids)
```

**Security rule:** `telegram_enabled=True` with an empty allowed-users list is
valid only for `/whoami`; all control commands fail closed until at least one ID
is configured.

**Verify:** `Settings(telegram_allowed_users="123,456").telegram_allowed_user_ids`
returns `frozenset({123, 456})`.

---

## Step 15: Create Telegram DI factory/control plane

**File:** `finbot/startup/telegram.py`

Create a `TelegramControlPlane` class that owns the Telegram asyncio loop and
background thread. This avoids relying on `asyncio.create_task()` inside MCP
startup, where there may be no running event loop yet.

Responsibilities:
- Create `PythonTelegramBotAdapter`
- Create `TelegramNotificationSender`
- Create `ThreadSafeTelegramNotificationDispatcher`
- After `BotManager` exists, attach command handlers with `HandleTelegramCommand`
- Start/stop PTB polling on a dedicated daemon thread with its own event loop

Factory shape:

```python
def create_telegram_control_plane(
    settings: Settings,
    chat_repo: TelegramChatRepository,
) -> TelegramControlPlane | None:
    if not settings.telegram_enabled:
        return None
    token = settings.telegram_bot_token.get_secret_value()
    if not token:
        raise ValueError("FINBOT_TELEGRAM_BOT_TOKEN is required when Telegram is enabled")
    return TelegramControlPlane(settings=settings, chat_repo=chat_repo)
```

After `BotManager` is created:

```python
telegram.attach_bot_manager(bot_manager)
telegram.start_in_background()
notification_sender = telegram.notification_dispatcher
```

`HandleTelegramCommand` dependencies must be:

```python
command_use_case = HandleTelegramCommand(
    bot_manager=bot_manager,
    chat_repo=chat_repo,
    strategy_dir=FilesystemStrategyDirectory(settings.telegram_strategies_dir),
    session_store=InMemoryTelegramSessionStore(),
    allowed_users=settings.telegram_allowed_user_ids,
    live_trading_ack=settings.live_trading_ack,
)
```

Notice: no `bot_port` dependency. The presentation handler sends returned DTOs.

---

## Step 16: Wire Telegram into MCP startup

**File:** `finbot/startup/mcp.py` (MODIFIED)

Use a dedicated Telegram background thread, not `asyncio.create_task()` from
`create_server()`. `create_server()` may run before there is an active event loop.

Startup order:

```python
settings = Settings()
repo = create_bot_state_repository(migrate=True)
exchange = create_exchange_gateway(settings)

telegram = None
notification_sender = None
if settings.telegram_enabled:
    chat_repo = SqliteTelegramChatRepository(settings.database_path)
    telegram = create_telegram_control_plane(settings, chat_repo)
    notification_sender = telegram.notification_dispatcher if telegram else None

bot_manager = BotManager(
    runtime_factory=_make_runtime_factory(settings, notification_sender),
    repository=repo,
    exchange=exchange,
    settings=settings,
    create_bot_config=lambda s: create_bot_config(s),
    startup_time=time.time(),
)

if telegram is not None:
    telegram.attach_bot_manager(bot_manager)
    telegram.start_in_background()
```

`_make_runtime_factory()` must pass `notification_sender` into
`create_live_trading_runtime_use_case(...)`, and that factory must pass it to
`AccountEventHandler` / `LiveTradingRuntimeUseCase` as needed.

Store the Telegram control plane on the FastMCP server instance so it is not
garbage-collected:

```python
server._finbot_telegram = telegram
```

**Common mistakes:**
- Calling `asyncio.create_task()` before an event loop exists.
- Starting PTB polling before command handlers are attached.
- Creating a second `BotManager` for Telegram instead of sharing the MCP one.

---

## Step 17: Add tests

| Test file | What it tests |
|-----------|---------------|
| `tests/test_domain/test_telegram_config.py` | Validation: empty token with enabled raises; allowed_users parsing; fail-closed empty allowed-users behavior |
| `tests/test_domain/test_telegram_run_flow_session.py` | Session expiry, compact callback data, selected strategy/symbol/interval/mode state |
| `tests/test_application/test_handle_telegram_command.py` | All commands with fakes; `/whoami`; unauthorized rejection; multi-step /run flow; live env ack + Telegram confirmation; bot-already-running rejection |
| `tests/test_application/test_send_bot_notification.py` | Formatting; sends to all chats; respects mute; handles empty chat list |
| `tests/test_infrastructure/test_python_telegram_bot_adapter.py` | Error classification (transient vs permanent); send_message/edit_message_text success/failure |
| `tests/test_infrastructure/test_sqlite_telegram_chat_repository.py` | CRUD; notifications toggle; list filtering; fresh schema creation |
| `tests/test_infrastructure/test_thread_safe_telegram_notification_dispatcher.py` | Scheduling from a non-async runtime thread onto a test asyncio loop |
| `tests/test_startup/test_telegram_control_plane.py` | Creates no bot when disabled; requires token when enabled; attaches BotManager before start; starts background thread without requiring existing event loop |
| `tests/test_presentation/test_bot_handler.py` | Command routing; callback routing; MarkdownV2 escaping; inline keyboard construction |
| `tests/test_presentation/test_notification_sender.py` | Trade/Risk/Error formatting; inline keyboard presence |

**All tests follow Classical (Detroit) school:** fake implementations for
external boundaries (`FakeTelegramBot`, `InMemoryTelegramChatRepository`,
`FakeBotManager`), real domain objects, assert on outcomes not interactions.
