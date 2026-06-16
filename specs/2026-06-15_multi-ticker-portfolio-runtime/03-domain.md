# Domain Model — Multi-Ticker Portfolio Runtime

All new types follow finbot's one-class-per-file rule and Clean Architecture
layering. Existing entities are referenced, not redefined.

## New Entities

### `Trade` — durable per-position record (the portfolio primitive)

This is the single most important addition. Today finbot has only a transient
`PositionSnapshot` (an exchange read) and scattered `OrderIntent` /
`FillRecord` rows. Multi-symbol demands a durable concept of "an open
position with a lifecycle" so portfolio risk can count open positions, exits
can target the right trade, and realized PnL survives across candles.

Distinct from `PositionSnapshot` (transient exchange state, read-only) and
`FillRecord` (a single fill). A `Trade` aggregates the entry/exit fills of
one position.

| Field               | Type                | Notes                                        |
|---------------------|---------------------|----------------------------------------------|
| position_id         | str                 | uuid4, primary key                           |
| bot_run_id          | str                 | which portfolio session opened it            |
| symbol              | str                 | e.g. "BTC"                                   |
| side                | PositionDirection   | LONG or SHORT (never FLAT — FLAT = no trade) |
| size                | Decimal             | filled size, base units                      |
| entry_price         | Decimal             | avg fill price of entry                      |
| opened_at           | datetime (UTC)      | first entry fill time                        |
| stop_price          | Decimal \| None     | from entry signal                            |
| target_price        | Decimal \| None     | from entry signal                            |
| max_favorable_price | Decimal \| None     | trailing-stop MFE (updated by runtime)       |
| max_adverse_price   | Decimal \| None     | MAE (for analytics)                          |
| strategy_hash       | str                 | links to the strategy that opened it         |
| entry_signal_key    | str                 | the signal that opened it (audit/idempotency)|
| status              | str                 | "open" \| "closed"                           |
| closed_at           | datetime \| None    | set on close                                 |
| close_price         | Decimal \| None     | avg fill price of exit                       |
| realized_pnl        | Decimal \| None     | computed on close                            |

**Behaviour:** pure dataclass (frozen). Lifecycle transitions live in a
`TradeLifecycle` domain service (see below), not on the entity — per finbot's
"entities are pure data" rule and to avoid an anemic-vs-fat tension.

**Persisted:** Yes — new SQLite table `trades`. Mapper in
`infrastructure/repositories/`.

**File:** `finbot/core/domain/entities/trade.py`

```python
@dataclass(frozen=True)
class Trade:
    position_id: str
    bot_run_id: str
    symbol: str
    side: PositionDirection          # LONG or SHORT
    size: Decimal
    entry_price: Decimal
    opened_at: datetime
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
    max_favorable_price: Decimal | None = None
    max_adverse_price: Decimal | None = None
    strategy_hash: str = ""
    entry_signal_key: str = ""
    status: str = "open"             # "open" | "closed"
    closed_at: datetime | None = None
    close_price: Decimal | None = None
    realized_pnl: Decimal | None = None
```

> **Naming note:** `Trade` is chosen over `Position` to avoid collision with
> the existing transient `PositionSnapshot` and `PositionDirection`. A
> "trade" = the durable lifecycle record of one position (entry → exit).
> This matches freqtrade's terminology without importing its 2,161-line
> structure.

---

## New Domain Services

### `SymbolPipeline` — one symbol's per-candle pipeline (extracted)

The per-symbol processing currently embedded in `LiveTradingRuntimeUseCase`
(warmup → enrich → validate → evaluate → risk → plan → persist → submit) is
extracted into a class parameterised by **one symbol**. Each pipeline owns
its own `WarmupWindow` and enriched frame (Slice 1). Slice 3's
`MarketDataProvider` later hoists this state out so pipelines share it.

**File:** `finbot/core/domain/services/symbol_pipeline.py`

```
class SymbolPipeline:
    """Processes closed candles for ONE symbol through the full pipeline."""

    symbol: str
    interval: str

    def __init__(self, *,
        symbol: str, interval: str, bot_run_id: str, mode: TradingMode,
        evaluator: StrategyEvaluator,
        indicator_calc: IndicatorCalculator,
        bar_converter: BarFrameConverter,
        enrichment_validator: EnrichmentValidator,
        order_planner: OrderPlanner,        # portfolio+per-symbol gates wired in
        repo: BotStateRepository,
        trade_book: TradeBook,              # open/close Trade entities
        cloid_gen: CloidGenerator | None,
        submitter: OrderSubmitter,
        warmup: WarmupWindow,
        required_columns, required_indicators,
    ): ...

    def process_candle(self, candle: dict) -> CandleProcessingResult:
        """warmup → enrich → validate → evaluate → (risk+plan via order_planner)
        → persist → submit. Returns the per-candle outcome."""

    # Read-only accessors (seed for MarketDataProvider in Slice 3):
    @property
    def warmup_count(self) -> int: ...
    @property
    def is_ready(self) -> bool: ...
    @property
    def enriched_frame(self) -> Any | None: ...
    @property
    def last_analyzed_timestamp(self) -> int | None: ...
```

**Purity:** Like `BotManager`, it depends only on domain interfaces + stdlib.
It holds DataFrame state via the `BarFrameConverter` abstraction (the pandas
type never leaks into the domain type signatures — it is `Any`).

### `PortfolioTradingRuntimeUseCase` — the multi-symbol coordinator

Owns a `dict[str, SymbolPipeline]`, demultiplexes candles by symbol, builds
the **portfolio context** (open-position count, gross notional, open-order
count across all symbols) before each gate evaluation, and owns the kill
switch + startup reconciliation.

**File:** `finbot/core/application/use_cases/portfolio_trading_runtime.py`

```
class PortfolioTradingRuntimeUseCase:
    """Runs one strategy across a symbol set with a shared risk budget."""

    def __init__(self, *,
        symbol_pipelines: dict[str, SymbolPipeline],
        exchange: ExchangeGateway,
        repo: BotStateRepository,
        trade_book: TradeBook,
        symbol_set_provider: SymbolSetProvider,
        mode: TradingMode,
        bot_loop: BotLoop | None,           # extended multi-symbol loop
    ): ...

    def start(self, *, strategy_path, symbols, interval) -> str: ...
    def start_live(self, *, strategy_path, symbols, interval, config) -> RunBotResult: ...
    def stop(self) -> None: ...

    def run_forever(self) -> None:
        """bot_loop feeds (symbol, candle); demuxed to pipelines."""

    def process_closed_candle(self, symbol: str, candle: dict) -> CandleProcessingResult:
        """Demux to pipelines[symbol], after injecting portfolio context."""

    def reconcile_on_startup(self, symbols) -> list[ReconciliationRecord]: ...

    def kill_switch(self, *, cancel_all: bool, close_all: bool) -> KillSwitchResult: ...

    def portfolio_status(self) -> PortfolioStatusSnapshot: ...
    def active_symbols(self) -> list[str]: ...   # static ∪ symbols-with-open-trades
    def symbol_status(self, symbol: str) -> str: ...  # "ok" | "degraded"
```

**Portfolio context building (the key new responsibility):**
```
def _portfolio_context(self, symbol, bar, position) -> dict:
    return {
        # per-symbol (existing gates)
        "bar": bar, "symbol": symbol, "mode": self._mode.value,
        "position_size": position.size,
        "open_order_count": len(self._exchange.list_open_orders(symbol)),
        "daily_loss_usd": self._trade_book.daily_realized_loss(),
        # portfolio-wide (new gates) — the core addition
        "portfolio_open_position_count": self._trade_book.count_open(),
        "portfolio_gross_notional_usd": self._trade_book.gross_notional(),
        "portfolio_open_order_count": self._exchange.count_all_open_orders(),
    }
```

### `TradeBook` — the open-position ledger (domain service)

Reads/writes `Trade` entities via the repository and answers portfolio
queries the gates need. Keeps portfolio aggregation logic in one tested place
rather than scattered across the runtime.

**File:** `finbot/core/domain/services/trade_book.py`

```
class TradeBook:
    """Portfolio ledger of open/closed Trade entities."""

    def __init__(self, repo: BotStateRepository): ...

    def open_trade(self, trade: Trade) -> None: ...
    def close_trade(self, position_id, *, close_price, closed_at) -> Trade: ...
    def get_open_for_symbol(self, symbol: str) -> Trade | None: ...
    def count_open(self) -> int: ...
    def gross_notional(self) -> Decimal: ...      # sum |size * entry_price|
    def daily_realized_loss(self) -> Decimal: ...
```

### `TradeLifecycle` — state transitions on Trade entities

Pure functions that produce new immutable `Trade` instances from events
(entry fill, exit fill, MFE/MAE update). Keeps the entity anemic and the
transition rules testable in isolation.

**File:** `finbot/core/domain/services/trade_lifecycle.py`

```
def apply_entry_fill(trade: Trade, fill: FillRecord) -> Trade: ...
def apply_exit_fill(trade: Trade, fill: FillRecord) -> Trade: ...
    # computes realized_pnl = (close-entry)*size * (+1 long / -1 short)
def update_extremes(trade: Trade, current_price: Decimal) -> Trade: ...
    # updates max_favorable_price / max_adverse_price
```

---

## New Portfolio Risk Gates

Live in `finbot/core/domain/services/risk_gates/` alongside the existing
per-symbol gates. Same `RiskGate` interface, same chain semantics. They read
**portfolio-wide** fields from the context dict.

### `MaxOpenPositionsGate`
**File:** `finbot/core/domain/services/risk_gates/max_open_positions_gate.py`
```
class MaxOpenPositionsGate(RiskGate):
    def __init__(self, max_positions: int = 0): ...  # 0 = disabled (unlimited)
    def check(self, signal, ctx) -> RiskDecision:
        # Bypass for exit signals (LONG_EXIT, SHORT_EXIT) — exits reduce count.
        # Reads ctx["portfolio_open_position_count"].
```

### `MaxGrossNotionalGate`
**File:** `finbot/core/domain/services/risk_gates/max_gross_notional_gate.py`
```
class MaxGrossNotionalGate(RiskGate):
    def __init__(self, max_gross_usd: Decimal = Decimal("0")): ...
    def check(self, signal, ctx) -> RiskDecision:
        # Bypass for exit signals. Reads ctx["portfolio_gross_notional_usd"]
        # and ctx["proposed_notional_usd"]; rejects if sum > max.
```

**Gate chain ordering (startup factory):**
```
portfolio gates (book-wide)  →  per-symbol gates  →  submit
[ MaxOpenPositions, MaxGrossNotional, DailyLoss ]  →  [ MaxPosition, MaxOpenOrders,
                                                        MaxLeverage, ReduceOnly,
                                                        StaleData, DuplicateSignal, Mode ]
```

---

## New / Changed Interfaces (for DI)

### `SymbolSetProvider` (new) — Strategy pattern
**File:** `finbot/core/domain/interfaces/symbol_set_provider.py`
```
class SymbolSetProvider(ABC):
    @abstractmethod
    def symbols(self) -> list[str]: ...
    @abstractmethod
    def refresh(self) -> None: ...   # no-op for static; live for dynamic
```
**MVP impl:** `StaticSymbolSetProvider` (`finbot/core/domain/services/static_symbol_set_provider.py`)
— reads a configured list. **Slice 3 impls:** `VolumePairlistProvider`, etc.

### `BotLoop` (changed) — multi-symbol contract
**File:** `finbot/core/domain/interfaces/bot_loop.py` (modified)
```
class BotLoop(ABC):
    @abstractmethod
    def start(
        self,
        symbols: list[str],              # was: symbol: str
        interval: str,
        on_candle: Callable[[str, dict[str, Any]], None],   # was: (dict)
        on_stale: Callable[[str, dict[str, Any]], None] | None = None,
        on_account_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None: ...
```
The callback now receives the symbol. `BotEventLoop` subscribes once per
symbol on a single shared `MarketDataStream` and tags each candle.

### `BotStateRepository` (extended) — Trade persistence
**File:** `finbot/core/domain/interfaces/bot_state_repository.py` (modified)

New methods (house style: extend the single state repo rather than add a
second interface; a future refactor may split a `TradeRepository` if it grows):
```
def open_trade(self, trade: Trade) -> None: ...
def close_trade(self, position_id: str, *, close_price: Decimal,
                closed_at: datetime, realized_pnl: Decimal) -> Trade: ...
def update_trade_extremes(self, position_id: str, *,
                          max_favorable: Decimal, max_adverse: Decimal) -> None: ...
def get_open_trade(self, symbol: str) -> Trade | None: ...
def list_open_trades(self) -> list[Trade]: ...
def list_closed_trades(self, *, bot_run_id: str | None = None) -> list[Trade]: ...
def count_open_trades(self) -> int: ...
def list_reconciliations(self, *, bot_run_id: str | None = None) -> list[ReconciliationRecord]: ...
```

### `ExchangeGateway` (extended) — portfolio queries
**File:** `finbot/core/domain/interfaces/exchange_gateway.py` (modified)
```
def get_all_positions(self, symbols: list[str]) -> list[PositionSnapshot]: ...
def count_all_open_orders(self, symbols: list[str]) -> int: ...
def cancel_all_orders(self) -> dict[str, object]: ...   # across all symbols
def close_all_positions(self) -> dict[str, object]: ... # reduce-only market
```

### `MarketDataProvider` (new, Slice 3 seed only)
**File:** `finbot/core/domain/services/market_data_provider.py` (created in Slice 3)

Central per-symbol state cache (freqtrade's `DataProvider` equivalent). Not
built in Slice 1 — `SymbolPipeline` owns its own state for the MVP. Designed
so Slice 3 can hoist it out without breaking the pipeline contract
(pipelines already expose `warmup_count` / `enriched_frame` / `is_ready`).

---

## New DTOs

All in `finbot/core/application/dto/`, one per file:

| DTO | Fields | Used by |
|-----|--------|---------|
| `PortfolioStatusSnapshot` | bot_run_id, symbols, per_symbol: dict[str, SymbolStatus], portfolio_open_positions, portfolio_gross_notional_usd, portfolio_open_order_count | `portfolio_status()` |
| `SymbolStatus` | symbol, warmup_ready, last_signal_action, last_candle_timestamp, position_direction, position_size, degraded: bool | nested in snapshot |
| `KillSwitchRequest` | cancel_all: bool, close_all: bool | MCP tool |
| `KillSwitchResult` | orders_cancelled: int, positions_closed: list[str], errors: dict[str, str] | MCP tool |
| `StartPortfolioRequest` | strategy_path, symbols: list[str], interval, mode, warmup_bars, live_trading_ack | MCP tool |

---

## Entity vs ORM separation

| Domain entity | ORM model | Mapper |
|---------------|-----------|--------|
| `Trade` (`core/domain/entities/trade.py`) | `TradeOrm` (`infrastructure/tables/trade.py` or in repo) | `trade_mapper.py` in `infrastructure/repositories/` |

`TradeOrm` is the SQLite/SQLAlchemy row; `Trade` is the pure dataclass. Never
imported as bare `Trade` outside the mapper. Consistent with existing
`PositionSnapshot` / `OrderIntent` separation.

---

## Files to Add / Modify

### New files (Slice 1)
| File | Layer |
|------|-------|
| `finbot/core/domain/entities/trade.py` | domain |
| `finbot/core/domain/services/symbol_pipeline.py` | domain |
| `finbot/core/domain/services/trade_book.py` | domain |
| `finbot/core/domain/services/trade_lifecycle.py` | domain |
| `finbot/core/domain/services/static_symbol_set_provider.py` | domain |
| `finbot/core/domain/services/risk_gates/max_open_positions_gate.py` | domain |
| `finbot/core/domain/services/risk_gates/max_gross_notional_gate.py` | domain |
| `finbot/core/domain/interfaces/symbol_set_provider.py` | domain |
| `finbot/core/application/use_cases/portfolio_trading_runtime.py` | application |
| `finbot/core/application/dto/portfolio_status_snapshot.py` | application |
| `finbot/core/application/dto/symbol_status.py` | application |
| `finbot/core/application/dto/kill_switch_request.py` | application |
| `finbot/core/application/dto/kill_switch_result.py` | application |
| `finbot/core/application/dto/start_portfolio_request.py` | application |
| `finbot/infrastructure/tables/trade.py` (or in-repo ORM) | infrastructure |
| `finbot/infrastructure/repositories/trade_mapper.py` | infrastructure |
| `tests/test_domain/test_trade_lifecycle.py` | tests |
| `tests/test_domain/test_max_open_positions_gate.py` | tests |
| `tests/test_domain/test_max_gross_notional_gate.py` | tests |
| `tests/test_application/test_portfolio_runtime.py` | tests |

### Modified files (Slice 1)
| File | Change |
|------|--------|
| `finbot/core/domain/interfaces/bot_loop.py` | `start(symbols, ..., on_candle(symbol, candle))` |
| `finbot/infrastructure/adapters/bot_event_loop.py` | subscribe to N symbols, tag candles, demux |
| `finbot/core/domain/interfaces/bot_state_repository.py` | add Trade + reconciliation methods |
| `finbot/infrastructure/repositories/in_memory_bot_state_repository.py` | implement new methods |
| `finbot/infrastructure/repositories/sqlite_bot_state_repository.py` | implement + `trades` table + migration |
| `finbot/infrastructure/repositories/sqlite_migrator.py` | migration for `trades` table |
| `finbot/core/domain/interfaces/exchange_gateway.py` | add portfolio query/cancel/close methods |
| `finbot/infrastructure/adapters/hyperliquid_exchange_gateway.py` | implement portfolio methods |
| `finbot/infrastructure/adapters/dry_run_exchange_gateway.py` | implement portfolio methods |
| `finbot/core/domain/services/bot_manager.py` | own `PortfolioTradingRuntimeUseCase` |
| `finbot/core/domain/entities/bot_run.py` | add `symbols: tuple[str, ...]` field |
| `finbot/config/settings.py` | add `symbols: list[str]`, `max_open_positions`, `max_gross_notional_usd` |
| `finbot/core/domain/entities/bot_config.py` | add portfolio risk fields |
| `finbot/startup/service_factory.py` | wire portfolio runtime + gate chain |
| `finbot/presentation/mcp/tools/bot_control.py` | `start_portfolio`, `kill_switch`, `portfolio_status` |
| `README.md` | replace "Multi-Ticker" section |

### Kept (degenerate single-symbol path)
`finbot/core/application/use_cases/live_trading_runtime.py` — preserved. A
portfolio runtime with one symbol behaves equivalently; the old use case
remains available and its tests stay green during the refactor.
