# Implementation Guide — Live YAML Trading Runtime

Follow Red → Green → Refactor per scenario. Use fakes/in-memory repositories in tests. Do not mock domain objects. Run `ruff`, `black --check`, and `pytest` after each slice.

---

## Slice 1 — Live-data dry-run runtime loop

### Step 1: Add live runtime request/result DTOs
**Files:**
- `finbot/core/application/dto/live_trading_request.py`
- `finbot/core/application/dto/live_trading_result.py`
- `finbot/core/application/dto/candle_processing_result.py`

Create frozen dataclass DTOs for starting the runtime and reporting per-candle processing outcomes.

**Skeleton:**
```python
from dataclasses import dataclass
from decimal import Decimal

from finbot.core.domain.entities.trading_mode import TradingMode


@dataclass(frozen=True)
class LiveTradingRequest:
    strategy_path: str
    symbol: str
    interval: str
    mode: TradingMode
    live_data: bool = True
    max_position_usd: Decimal = Decimal("0")
```

**Verify:**
```bash
pytest tests/test_application -k live_trading_request -q
```

**Common mistake:** Do not import infrastructure adapters in DTO files.

---

### Step 2: Create `LiveTradingRuntimeUseCase`
**File:** `finbot/core/application/use_cases/live_trading_runtime.py`

This use case owns runtime orchestration. Inject all dependencies through the constructor:

- `StrategyDefinitionLoader`
- `StrategyEvaluatorFactory`
- `StrategyValidator` or compatibility checker
- `BarSource`
- `MarketDataStream`
- `EventQueue`
- `ExchangeGateway`
- `BotStateRepository`
- `MarketMetadataProvider`
- `IndicatorCalculator`
- `OrderPlanner`
- `OrderNormalizer`
- `LiveModeGuard`

Public methods:

```python
class LiveTradingRuntimeUseCase:
    def start(self, request: LiveTradingRequest) -> LiveTradingResult: ...
    def stop(self) -> None: ...
    def process_closed_candle(self, bar: dict) -> CandleProcessingResult: ...
    def process_account_event(self, event: dict) -> AccountEventProcessingResult: ...
```

**Verify:**
```bash
pytest tests/test_application/test_live_trading_runtime.py -q
```

**Common mistake:** Do not instantiate `HyperliquidMarketDataStream`, `SqliteBotStateRepository`, or `RuleBasedStrategyEvaluator` inside the use case. Use constructor injection and startup factories.

---

### Step 3: Write application tests with fakes
**File:** `tests/test_application/test_live_trading_runtime.py`

Add fakes:

- `FakeMarketDataStream`
- `InMemoryBarSource`
- `InMemoryIndicatorCalculator`
- `InMemoryExchangeGateway`
- `InMemoryBotStateRepository`
- `FakeStrategyEvaluatorFactory`

First tests:

```python
def test_live_data_dry_run_processes_closed_candle_without_submit(): ...
def test_runtime_rejects_invalid_strategy_before_subscribe(): ...
def test_runtime_skips_evaluation_until_warmup_ready(): ...
def test_duplicate_closed_candle_does_not_duplicate_signal(): ...
```

**Verify:**
```bash
pytest tests/test_application/test_live_trading_runtime.py -q
```

**Common mistake:** Do not use `MagicMock.assert_called_once`. Assert on repository and fake gateway state.

---

### Step 4: Wire `BotEventLoop` into runtime start
**File:** `finbot/core/application/use_cases/live_trading_runtime.py`

The use case can depend on a small domain/application interface for event loops, or startup can pass a `BotEventLoop`-like runner. Keep infrastructure out of application by introducing a domain interface if needed:

**File:** `finbot/core/domain/interfaces/bot_loop.py`

```python
from abc import ABC, abstractmethod


class BotLoop(ABC):
    @abstractmethod
    def start(self, symbol: str, interval: str) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
```

Then make `BotEventLoop` implement it.

**Verify:**
```bash
pytest tests/test_architecture/test_dependency_rules.py -q
pytest tests/test_infrastructure/test_bot_event_loop.py -q
```

**Common mistake:** Do not import `finbot.infrastructure.adapters.bot_event_loop` in the application layer.

---

## Slice 2 — Real YAML strategy runtime wiring

### Step 5: Replace placeholder evaluator in startup factory
**File:** `finbot/startup/service_factory.py`

Stop wiring `FinbarStrategyEvaluator` for live/replay runtime. Load YAML with `YamlStrategyDefinitionLoader`, hash the strategy content, and use `RuleBasedStrategyEvaluatorFactory`.

**Target flow:**
```python
loader = YamlStrategyDefinitionLoader()
definition = loader.load_from_file(strategy_path)
strategy_hash = hash_strategy_file(strategy_path)
evaluator = RuleBasedStrategyEvaluatorFactory().create(
    definition=definition,
    symbol=symbol,
    interval=interval,
    strategy_hash=strategy_hash,
)
```

**Verify:**
```bash
pytest tests/test_startup -q
pytest tests/test_application/test_live_trading_runtime.py -q
```

**Common mistake:** Do not revive a Finbar runtime dependency. Production code must still have zero `finbar.*` imports.

---

### Step 6: Add startup compatibility gate
**Files:**
- `finbot/core/application/use_cases/live_trading_runtime.py`
- `tests/test_application/test_live_trading_runtime.py`

Before subscribing to market data:

1. Load YAML.
2. Validate strategy.
3. Check compatibility for target mode.
4. Reject unsupported indicators/operators/risk settings.

**Verify:**
```bash
pytest tests/test_application/test_live_trading_runtime.py -k compatibility -q
```

**Common mistake:** Do not subscribe to websockets before validation passes.

---

## Slice 3 — Live indicator enrichment

### Step 7: Add historical warmup before subscribing
**File:** `finbot/core/application/use_cases/live_trading_runtime.py`

At startup:

1. Load closed historical bars through `BarSource`.
2. Append to `WarmupWindow`.
3. Reject or wait if warmup is not ready.
4. Only after readiness subscribe to live candles.

**Verify:**
```bash
pytest tests/test_application/test_live_trading_runtime.py -k warmup -q
pytest tests/test_infrastructure/test_warmup_window.py -q
```

**Common mistake:** Do not evaluate the first live candle if required indicators are missing.

---

### Step 8: Add the enrichment validation gate
**Files:**
- `finbot/core/domain/entities/enrichment_validation_result.py`
- `finbot/core/domain/services/enrichment_validator.py`
- `tests/test_domain/test_enrichment_validator.py`

Create a pure domain service that validates the latest enriched bar before strategy evaluation.

**Rules:**

1. Required columns are derived from the parsed strategy definition.
2. Every required column must be present in the latest enriched bar.
3. Every required latest value must be non-null.
4. Numeric required values must be finite: no `NaN`, `inf`, or `-inf`.
5. Boolean required values must be real booleans or accepted numeric boolean equivalents only if the strategy expects that shape.
6. Optional/non-required columns do not block evaluation.
7. Warmup must be ready and gap-free.
8. The candle must be closed before this validator is called.

**Skeleton:**
```python
from dataclasses import dataclass, field
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class EnrichmentValidationResult:
    valid: bool
    missing_columns: list[str] = field(default_factory=list)
    non_finite_columns: list[str] = field(default_factory=list)
    invalid_type_columns: list[str] = field(default_factory=list)
    reason: str = ""


class EnrichmentValidator:
    def validate(
        self,
        enriched_bar: dict[str, Any],
        required_columns: set[str],
        warmup_ready: bool,
        has_gap: bool,
    ) -> EnrichmentValidationResult:
        ...
```

**Verify:**
```bash
pytest tests/test_domain/test_enrichment_validator.py -q
```

**Common mistake:** Do not let pandas `NaN` pass just because the column exists. Existing column with unusable value must reject the candle.

---

### Step 9: Enrich and validate each closed live candle
**File:** `finbot/core/application/use_cases/live_trading_runtime.py`

`process_closed_candle()` should:

1. Append the raw closed candle to `WarmupWindow`.
2. Ask `IndicatorCalculator` for enriched bars/latest bar.
3. Derive required strategy columns from `StrategyDefinition` / evaluator metadata.
4. Run `EnrichmentValidator`.
5. If validation fails, persist an audit/risk event and return without evaluating the strategy.
6. Pass the latest enriched bar to `StrategyEvaluator` only when validation passes.

**Verify:**
```bash
pytest tests/test_application/test_live_trading_runtime.py -k "enrich or enrichment" -q
pytest tests/test_domain/test_enrichment_validator.py -q
```

**Common mistake:** Do not pass raw OHLCV directly to the strategy evaluator for AMT strategies. Do not evaluate a bar with missing, NaN, or infinite required indicator values.

---

## Slice 4 — Dry-run order simulation

### Step 10: Process signal into risk decision and order intent
**File:** `finbot/core/application/use_cases/live_trading_runtime.py`

For each non-HOLD signal:

1. Build deterministic signal key.
2. Check duplicate signal persistence.
3. Call `OrderPlanner` / risk gate chain.
4. Persist risk event.
5. If accepted, persist order intent.
6. In dry-run mode, update simulated position state without exchange submission.

**Verify:**
```bash
pytest tests/test_application/test_live_trading_runtime.py -k dry_run -q
pytest tests/test_domain/test_order_planner.py -q
```

**Common mistake:** Do not submit orders in dry-run. Assert fake exchange submitted count remains zero.

---

### Step 11: Persist audit events for every decision
**Files:**
- `finbot/core/application/use_cases/live_trading_runtime.py`
- `finbot/core/domain/interfaces/bot_state_repository.py`
- `finbot/infrastructure/repositories/sqlite_bot_state_repository.py` if methods are missing

Persist:

- session started/stopped
- warmup ready/not ready
- signal evaluated
- risk accepted/rejected
- order intent created
- dry-run simulated fill/position update if applicable

**Verify:**
```bash
pytest tests/test_application/test_observability.py -q
pytest tests/test_infrastructure/test_sqlite_bot_state_repository.py -q
```

**Common mistake:** Do not rely only on logs. State must be queryable by `finbot status`.

---

## Slice 5 — Testnet execution

### Step 12: Normalize and submit accepted intents in testnet mode
**File:** `finbot/core/application/use_cases/live_trading_runtime.py`

For testnet mode:

1. Fetch `MarketMetadata`.
2. Normalize intent size/price.
3. Require `cloid`.
4. Persist intent before submit.
5. Submit through `ExchangeGateway`.
6. Persist response after submit.
7. Reconcile position/open orders.

**Verify:**
```bash
pytest tests/test_application/test_live_trading_runtime.py -k testnet -q
pytest tests/test_infrastructure/test_hyperliquid_exchange_gateway.py -q
```

**Common mistake:** Do not retry order submission without `cloid`.

---

### Step 13: Add CLI flags for runtime modes
**File:** `finbot/presentation/cli/main.py`

Clarify command shape. Suggested:

```bash
finbot run --strategy path.yaml --symbol BTC --interval 1h --mode dry_run --live-data
finbot run --strategy path.yaml --symbol BTC --interval 1h --mode testnet
finbot run --strategy path.yaml --symbol BTC --interval 1h --mode live
```

If mode remains env-driven, still expose safe CLI output that clearly states resolved mode.

**Verify:**
```bash
pytest tests/test_presentation -q
```

**Common mistake:** Do not allow mainnet when `FINBOT_MODE != live`.

---

## Slice 6 — Account websocket events

### Step 14: Extend market/account stream adapter for account events
**File:** `finbot/infrastructure/adapters/hyperliquid_market_data_stream.py` or a new `hyperliquid_account_data_stream.py`

Subscribe to:

- `userFills`
- `orderUpdates`
- optionally `webData2`

Normalize SDK messages into `BotEvent(type=ORDER_UPDATE/FILL, data=...)`.

**Verify:**
```bash
pytest tests/test_infrastructure/test_hyperliquid_market_data_stream.py -q
pytest tests/test_infrastructure/test_bot_event_loop.py -q
```

**Common mistake:** Do not silently drop account/order/fill events when the queue is full. Either block briefly, persist emergency audit, or force reconciliation state.

---

### Step 15: Process account events into lifecycle state
**Files:**
- `finbot/core/application/use_cases/live_trading_runtime.py`
- `finbot/core/domain/services/order_state_machine.py`
- `finbot/infrastructure/repositories/sqlite_bot_state_repository.py`

Map order updates/fills to lifecycle transitions and persisted fills.

**Verify:**
```bash
pytest tests/test_application/test_live_trading_runtime.py -k account_event -q
pytest tests/test_domain/test_order_state_machine.py -q
```

**Common mistake:** Do not make duplicate fill events create duplicate fill records.

---

## Slice 7 — Controlled live rollout

### Step 16: Enforce live-mode gate inside the new runtime
**File:** `finbot/core/application/use_cases/live_trading_runtime.py`

Before websocket subscription, live mode must check:

- `FINBOT_MODE=live`
- `FINBOT_LIVE_TRADING_ACK=true`
- private key present and valid
- durable DB path, not in-memory
- positive max position and daily loss limits
- startup reconciliation success
- strategy compatibility success
- no unknown order lifecycle states

**Verify:**
```bash
pytest tests/test_domain/test_live_mode_guard.py -q
pytest tests/test_application/test_live_trading_runtime.py -k live_mode -q
```

**Common mistake:** Do not start market data subscription if any blocker exists.

---

### Step 17: Full regression and architecture review
**Files:** all touched files

Run:

```bash
ruff check finbot tests
black --check finbot tests
pytest tests
```

Then run architecture/spec review manually:

- Dependency direction: domain/application must not import infrastructure.
- Domain entities stay pure.
- Live/testnet/dry-run share the same pipeline until submission boundary.
- Dry-run cannot submit.
- Live cannot start accidentally.

**Verify:**
```bash
ruff check finbot tests && black --check finbot tests && pytest tests
```

**Common mistake:** Do not accept passing unit tests if architecture tests fail.
