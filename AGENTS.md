# Code Guide — Finbot Live Trading Runtime

> **Instructions for AI coding assistants and human developers.** Finbot is a
> live trading runtime for strategies authored/backtested in Finbar. Treat this
> project as safety-critical software: correctness, observability, idempotency,
> and risk controls are more important than speed of implementation.

---

## Mission

Finbot connects to Hyperliquid, consumes real-time market/account data, evaluates
Finbar YAML/JSON strategies, places/monitors/modifies/cancels orders, reconciles
state after restarts, and enforces live risk controls.

Finbot must **not** duplicate Finbar's strategy SDK. Finbar remains the source of
truth for:

- strategy schema/parsing/validation
- indicator and feature calculation
- rule evaluation semantics
- risk stop/target calculation
- backtesting and optimization

Finbot owns:

- live websocket runtime
- exchange execution adapters
- order lifecycle management
- position reconciliation
- risk kill switches
- durable bot state and audit logs
- CLI/API control surfaces

---

## Non-Negotiable Trading Safety Rules

1. **Dry-run is the default.** New commands and configs must default to
   `dry_run`; never default to testnet/live order placement.
2. **Live trading requires explicit opt-in.** Live mode must require both a live
   mode setting and an explicit acknowledgment such as
   `FINBOT_LIVE_TRADING_ACK=true`.
3. **No secrets in code or tests.** Private keys, wallets, vault addresses, API
   keys, and mnemonic material come only from environment variables or ignored
   local files.
4. **Idempotency is mandatory.** Use Hyperliquid `cloid` for strategy-generated
   orders when possible. Prevent duplicate orders for the same closed candle and
   signal.
5. **Persist before/after external effects.** Record intent before sending an
   order and record the exchange response/fill/update afterwards.
6. **Reconcile on startup.** Always fetch current exchange positions/open orders
   before evaluating a strategy. Database state is not authoritative by itself.
7. **Reduce-only exits.** Exit/close orders must be reduce-only unless a use case
   explicitly proves another behavior is safe.
8. **Risk gates before every order.** Enforce max notional, max leverage, max
   open orders, max daily loss, stale-data checks, and mode checks before any
   execution adapter submits an order.
9. **Kill switch first-class.** There must be a clear path to cancel open orders
   and optionally market-close positions.
10. **Closed-bar execution by default.** Strategies run on closed candles unless
    a strategy/runtime config explicitly supports intrabar execution.

---

## Architecture Skeleton

Finbot follows **Clean Architecture** with dependencies flowing inward. Outer
layers may depend on inner layers; inner layers must not depend on outer layers.

```text
finbot/
├── core/
│   ├── domain/          # Pure entities, value objects, interfaces, risk rules
│   └── application/     # Use cases and DTOs; imports domain only
├── infrastructure/      # Hyperliquid, Finbar, SQL, filesystem implementations
├── presentation/        # CLI, REST API, event handlers, response formatting
├── startup/             # Composition root / dependency factories
└── config/              # Configuration loading and validation
```

### Dependency Rules

| Layer | May Import From | Must Not Import |
|-------|-----------------|-----------------|
| `core/domain/` | stdlib, typing, dataclasses, decimal | Finbar, Hyperliquid SDK, SQLAlchemy, FastAPI, config, infrastructure |
| `core/application/` | `core/domain/` | infrastructure, presentation, startup, Hyperliquid SDK |
| `infrastructure/` | `core/domain/` | presentation |
| `presentation/` | application, domain, startup factories | direct exchange/network logic |
| `startup/` | everything | n/a |
| `config/` | stdlib and config libraries | business logic |

**Golden rule:** Application use cases depend on domain interfaces, not concrete
Hyperliquid/Finbar/SQL implementations.

---

## External Integration Boundaries

### Hyperliquid SDK

- Only infrastructure adapters may import `hyperliquid.*`.
- Wrap SDK calls behind domain interfaces such as `ExchangeGateway` and
  `MarketDataStream`.
- Do not pass raw SDK responses into application/domain layers. Convert them to
  Finbot domain entities or DTOs.
- Every method that can place/modify/cancel orders must be covered by dry-run and
  risk checks at the application level.

### Finbar

- Only infrastructure adapters may import `finbar.*`.
- Finbot should consume Finbar through a narrow interface, e.g.
  `StrategyEvaluator`.
- Do not reimplement Finbar condition/risk semantics in Finbot unless adding a
  dedicated adapter test proving equivalence.
- Live enriched bars must match the structure expected by Finbar's
  `JsonRuleBasedStrategy.on_bar()`.

---

## Mandatory Design Patterns

### Dependency Injection

All dependencies are constructor-injected. No service locators, hard-coded
singletons, hidden global clients, or direct SDK construction in use cases.

### Repository Pattern

Durable state is accessed through repository interfaces in `core/domain/` and
implementations in `infrastructure/repositories/`.

### Strategy Pattern

Use interfaces for swappable behavior: strategy evaluation, order sizing,
execution mode, bar aggregation, risk gates, and reconciliation policies.

### Factory / Composition Root

Object graphs are created in `startup/`. Do not construct complex dependencies
inside use cases or presentation handlers.

### DTOs

Pure dataclass DTOs with no framework dependencies belong in
`core/domain/dto/`. DTOs that depend on framework types (e.g. Pydantic)
belong in `core/application/dto/`. API-specific request/response models
belong in `presentation/`.

### Pipeline / Extract Method

Any method over ~50 lines must be split into named private steps. Prefer a short
public dispatcher that reads like a workflow.

---

## One Class Per File — Strict Rule

Every class, interface, DTO, entity, enum, and strategy lives in its own
`snake_case.py` file matching the class name.

Examples:

```text
core/domain/entities/order_intent.py          -> class OrderIntent
core/domain/interfaces/exchange_gateway.py   -> class ExchangeGateway
core/application/dto/run_bot_request.py       -> class RunBotRequest
core/application/use_cases/run_bot.py         -> class RunBotUseCase
infrastructure/adapters/hyperliquid_gateway.py -> class HyperliquidGateway
```

Exceptions:

- `__init__.py`
- helper functions tightly coupled to the single class in the file
- file-level constants

---

## Coding Conventions

- Python 3.12+.
- Absolute imports from `finbot`.
- Public functions/classes require type hints and docstrings.
- Use `| None`, not `Optional`.
- Keep domain entities pure: no network, database, filesystem, environment, or
  framework access.
- Alias ORM models if they share names with domain entities.
- Prefer `Decimal` for money/notional/risk calculations in domain code.
- Use UTC timestamps.
- Use structured logging for bot/order/risk events.

---

## Testing Expectations

```text
tests/
├── test_domain/          # pure, no network/db/filesystem
├── test_application/     # use cases with fake interfaces
├── test_infrastructure/  # adapters with fakes/testnet/mocked SDK
└── test_presentation/    # CLI/API behavior
```

Minimum tests for trading features:

- dry-run never calls live exchange submission
- live mode requires explicit acknowledgment
- duplicate candle/signal does not duplicate orders
- reduce-only exit behavior
- stale-data kill switch
- startup reconciliation uses exchange state
- risk limits block oversized orders

---

## Development Commands

```bash
# from project root
python -m pip install -e ".[dev]"
ruff check finbot tests
black finbot tests
pytest tests
```

All code must pass ruff, black, and tests before being considered complete.

---

## Initial Feature Workflow

When adding functionality:

1. Define/extend a domain entity or interface.
2. Add DTOs if data crosses use-case boundaries.
3. Implement the application use case using only domain interfaces.
4. Implement infrastructure adapters/repositories.
5. Wire dependencies in `startup/`.
6. Expose through CLI/API in `presentation/`.
7. Add tests at the correct layer.
8. Update README/config examples if behavior changes.

---

## Review Checklist

Before committing, verify:

- [ ] No secrets or wallet keys are committed.
- [ ] Default mode is dry-run.
- [ ] Use cases import only domain/application modules.
- [ ] Hyperliquid and Finbar imports are infrastructure-only.
- [ ] Orders are idempotent where possible.
- [ ] Risk gates run before execution.
- [ ] Startup reconciliation is not bypassed.
- [ ] New classes follow one-class-per-file.
- [ ] Public APIs have type hints and docstrings.
- [ ] Tests cover dry-run and failure paths.
