# Domain Model — Live YAML Trading Runtime

This feature mostly composes existing domain entities and interfaces. New code should add only the minimum orchestration DTOs/entities needed to represent a running live session and per-candle processing outcome.

## Entities

| Entity | Fields | Behaviour | Persisted? |
|--------|--------|-----------|------------|
| `LiveTradingSession` | `session_id: str`, `bot_run_id: str`, `strategy_name: str`, `strategy_hash: str`, `symbol: str`, `interval: str`, `mode: TradingMode`, `started_at: datetime`, `status: str` | Represents a running runtime session; can be stopped | Yes, via `bot_runs`/audit log |
| `BotEvent` | `type: BotEventType`, `data: dict` | Carries normalized websocket events | No, events produce persisted effects |
| `StrategyDefinition` | Existing YAML-derived fields | Defines executable strategy shape | Snapshot persisted |
| `SignalDecision` | `action`, `symbol`, `interval`, `candle_timestamp`, `strategy_hash`, `confidence`, `stop_price`, `target_price` | Output of strategy evaluator | Yes, as processed signal/audit event |
| `OrderIntent` | `symbol`, `side`, `size`, `order_type`, `signal_key`, `reduce_only`, prices, `cloid` | Planned order before exchange submission | Yes |
| `RiskDecision` | decision/reason/context | Explains risk acceptance/rejection | Yes, via risk events |
| `OrderLifecycle` | `intent_id`, `state`, fill/remaining data | Validates order state transitions | Yes |
| `FillRecord` | fill id/order id/symbol/side/size/price/fee/time | Records execution fills | Yes |
| `ReconciliationRecord` | bot run id, position/open order match, details | Captures restart/startup reconciliation | Yes |

## Value Objects

| Value Object | Fields | Used where |
|-------------|--------|------------|
| `SignalKey` | `strategy_hash`, `symbol`, `interval`, `candle_timestamp`, `action` | Duplicate prevention; can be a helper function/value object if not already present |
| `Cloid` | deterministic client order id string | Idempotent exchange submission |
| `WarmupReadiness` | `ready: bool`, `reason: str`, `bar_count: int` | Runtime decision before strategy evaluation |
| `EnrichmentValidationResult` | `valid: bool`, `missing_columns: list[str]`, `non_finite_columns: list[str]`, `invalid_type_columns: list[str]`, `reason: str` | Gate result before strategy evaluation |
| `ProcessingResult` | `signal`, `risk_decision`, `intent`, `submitted`, `message` | Per-candle outcome for tests and audit |

## Domain Events

| Event | Payload | Raised by |
|-------|---------|-----------|
| `LiveSessionStarted` | session id, strategy, symbol, interval, mode | Live runtime startup |
| `WarmupReady` | session id, bar count, min bars | Warmup service |
| `CandleIgnored` | candle timestamp, reason | Candle processor/warmup |
| `SignalEvaluated` | signal key, action, confidence, prices | Strategy runtime |
| `RiskDecisionRecorded` | signal key, decision, reason | Order planner/risk gate chain |
| `OrderIntentCreated` | intent id, signal key, cloid | Order planner |
| `OrderSubmitted` | intent id, cloid, exchange response status | Exchange submission pipeline |
| `OrderLifecycleChanged` | intent id, old state, new state | Account event processor/reconciler |
| `LiveSessionStopped` | session id, reason | Runtime shutdown |

## Interfaces (for DI / Repository pattern)

| Interface | Methods | Implemented by |
|-----------|---------|----------------|
| `StrategyDefinitionLoader` | `load_from_text(content)`, `load_from_file(path)` | `YamlStrategyDefinitionLoader` |
| `StrategyValidator` | validate/compatibility methods | Existing validator use case/service |
| `StrategyEvaluatorFactory` | `create(definition, symbol, interval, strategy_hash) -> StrategyEvaluator` | `RuleBasedStrategyEvaluatorFactory` |
| `StrategyEvaluator` | `evaluate(enriched_bar, position) -> SignalDecision`, `reset()` | `RuleBasedStrategyEvaluator` |
| `BarSource` | load historical closed bars | `HistCsvBarSource`, future Hyperliquid historical source |
| `MarketDataStream` | `subscribe_candles(symbol, interval, callback)`, `stop()` | `HyperliquidMarketDataStream`, fakes |
| `IndicatorCalculator` | calculate required indicator columns over bar window | `PandasTaIndicatorCalculator` or adapted existing engine |
| `EnrichmentValidator` | `validate(enriched_bar, required_columns, warmup) -> EnrichmentValidationResult` | Pure domain service in `core/domain/services/` |
| `EventQueue` | `enqueue`, `dequeue`, `size`, `clear` | `ThreadSafeEventQueue`, fake queue |
| `ExchangeGateway` | get position, list orders, submit, cancel | `DryRunExchangeGateway`, `HyperliquidExchangeGateway`, fakes |
| `MarketMetadataProvider` | metadata lookup | `HyperliquidMetadataProvider`, fake provider |
| `BotStateRepository` | bot runs, signals, intents, responses, fills, lifecycle, audit | `SqliteBotStateRepository`, in-memory fake |
| `DatabaseMigrator` | migrate/current_version | `SqliteMigrator` |

## New Application DTOs

| DTO | Fields | Purpose |
|-----|--------|---------|
| `LiveTradingRequest` | `strategy_path`, `symbol`, `interval`, `mode`, `live_data`, `dry_run`, `testnet`, config fields | Boundary input for runtime start |
| `LiveTradingResult` | `status`, `message`, `session_id`, `bot_run_id`, `blockers` | Startup outcome |
| `CandleProcessingResult` | `candle_timestamp`, `enrichment_valid`, `enrichment_errors`, `signal`, `risk_decision`, `intent_id`, `submitted`, `errors` | Testable outcome of one closed candle |
| `AccountEventProcessingResult` | `event_type`, `intent_id`, `old_state`, `new_state`, `persisted` | Testable account-event outcome |

## Entity vs ORM separation

- Domain entities stay in `finbot/core/domain/entities/` and must remain pure dataclasses/enums without SQLite, Hyperliquid, pandas, or Pydantic dependencies.
- SQLite tables are managed by `finbot/infrastructure/repositories/sqlite_migrator.py` and repository SQL in `sqlite_bot_state_repository.py`.
- Mapping between domain entities and SQLite rows belongs in infrastructure repository helper methods only.
- Hyperliquid SDK objects must never leak into domain/application DTOs. Adapters convert SDK dictionaries into domain entities or plain `dict[str, Any]` event payloads at the boundary.

## Invariants

- A strategy is never evaluated on a partial candle.
- A strategy is never evaluated before warmup readiness.
- A strategy is never evaluated unless enrichment validation passes.
- Enrichment validation must reject missing required columns, `None`, `NaN`, positive/negative infinity, and incompatible latest-bar value types.
- Optional/non-required columns may be missing or non-finite without blocking a decision.
- A signal key is persisted before any order submission attempt.
- Order submission retry is forbidden without `cloid`.
- Dry-run mode never calls a live/testnet exchange submit method.
- Live mode cannot start with in-memory persistence.
- Account/order/fill events must not be silently dropped.
