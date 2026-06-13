# Architecture Decisions — Live YAML Trading Runtime

## ADR-1: Add a dedicated live runtime use case

**Context:**
`RunBotUseCase` currently performs startup validation and returns. Wiring websocket loops, warmup, enrichment, strategy evaluation, risk gates, dry-run/testnet/live branching, account events, and shutdown into that class would turn it into a god use case.

**Decision:**
Create a dedicated `LiveTradingRuntimeUseCase` in `finbot/core/application/use_cases/live_trading_runtime.py`. Keep `RunBotUseCase` as a startup/safety check or eventually replace the CLI wiring to call the new runtime use case.

**Consequences:**
- Easier to test one closed-candle processing outcome at a time.
- More dependencies must be injected, so startup factory becomes more important.
- Prevents a long `RunBotUseCase.execute()` method.

---

## ADR-2: Use the real Finbot rule-based evaluator, not the Finbar placeholder

**Context:**
`FinbarStrategyEvaluator` is currently a placeholder that always returns HOLD. Finbot already has a standalone parser and `RuleBasedStrategyEvaluator` for supported YAML strategies.

**Decision:**
The live runtime must load YAML into `StrategyDefinition` and create `RuleBasedStrategyEvaluator` through `StrategyEvaluatorFactory`. `FinbarStrategyEvaluator` must not be in the live execution path.

**Consequences:**
- Finbot remains standalone at runtime.
- YAML strategy support is limited to validated/compatible Finbot-supported features.
- Unsupported Finbar YAML features reject startup clearly.

---

## ADR-3: SDK callbacks enqueue only; application runtime processes events

**Context:**
Hyperliquid websocket callbacks run on SDK-managed threads. Running strategy logic or exchange submission from callbacks risks race conditions and makes deterministic tests difficult.

**Decision:**
SDK callbacks normalize data and enqueue `BotEvent`s only. The runtime/event loop processes events sequentially on the main bot loop.

**Consequences:**
- Strategy and order processing are single-threaded and easier to reason about.
- Queue backpressure policy must be explicit.
- Account/order/fill events must not be silently dropped.

---

## ADR-4: Dry-run, testnet, and live share one pipeline until submission

**Context:**
If dry-run uses different logic from testnet/live, dry-run evidence is weak. The operator needs confidence that dry-run decisions match real submission decisions.

**Decision:**
Use the same path for candle processing, enrichment, strategy evaluation, signal keys, order planning, risk gates, and persistence. Branch only at the submission boundary:

- `dry_run`: persist/simulate, never submit.
- `testnet`: normalize and submit to testnet gateway.
- `live`: normalize and submit only after live gates pass.

**Consequences:**
- Dry-run becomes meaningful evidence for testnet/live.
- More care is needed to guarantee dry-run cannot submit.
- Fakes can test the full pipeline without network.

---

## ADR-5: Warmup, indicator enrichment, and enrichment validation are runtime requirements

**Context:**
The target AMT YAML strategies require enriched fields such as ATR, volume-profile levels, acceptance booleans, and value-area width filters. Live Hyperliquid candles provide raw OHLCV only. Indicator engines can sometimes return missing columns, `None`, `NaN`, or infinite values when there is insufficient data or an upstream calculation fails. A column merely existing is not enough to make a trading decision safe.

**Decision:**
Before subscribing or before first evaluation, load historical closed candles into `WarmupWindow`. Each new closed candle is appended and enriched through the indicator engine. Strategies are evaluated only after a hard enrichment validation gate passes.

The gate rejects evaluation when:

- warmup is not ready,
- the warmup window has gaps,
- the candle is not known to be closed,
- any required strategy column is missing,
- any required latest value is `None`, `NaN`, `inf`, or `-inf`,
- any required latest value has an incompatible type.

Optional/non-required columns do not block evaluation.

**Consequences:**
- Live and replay behaviour stay aligned.
- Runtime startup can reject/wait if warmup data is missing.
- Indicator engine errors become explicit operational blockers.
- The strategy evaluator receives only decision-grade enriched bars.
- Some candles may be skipped safely rather than forcing a low-confidence decision.

---

## ADR-6: Live mode requires durable persistence and reconciliation

**Context:**
Live trading without durable duplicate prevention and restart reconciliation can duplicate orders after process restart or leave unknown exchange state unmanaged.

**Decision:**
Live mode must reject startup unless durable SQLite persistence is configured, migrations are current, startup reconciliation succeeds, and no blocking unknown order lifecycle exists.

**Consequences:**
- Live cannot run with `InMemoryBotStateRepository`.
- Operators must run migrations before live.
- Recovery is safer but startup can fail more often with clear blockers.

---

## ADR-7: Account websocket events are eventually required for live correctness

**Context:**
REST reconciliation is sufficient for startup and periodic checks, but order lifecycle needs timely fill/order updates for correct position state and risk gates.

**Decision:**
After testnet submission works, add account websocket subscriptions for `userFills` and `orderUpdates`. These events update `OrderLifecycle` and persisted fills through the same event queue.

**Consequences:**
- Runtime state becomes more accurate between reconciliations.
- Event idempotency is required.
- Unknown/unmapped account events must force reconciliation-required state.
