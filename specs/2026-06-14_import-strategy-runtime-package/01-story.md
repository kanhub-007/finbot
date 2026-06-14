# Import Shared Strategy Runtime Package

## User Story
As a Finbot maintainer, I want Finbot to use the published shared strategy runtime package instead of copied Finbar code, so that live execution uses the same strategy semantics as Finbar authoring/backtesting while Finbot remains standalone and safe.

## Context
Finbot currently contains adapted copies of Finbar's parser, schema, domain strategy entities, indicator catalog, condition evaluator, risk calculator, and rule-based strategy evaluator. This avoided a runtime dependency on the Finbar service, but it makes semantic drift likely.

Finbot should depend on `finbar-strategy-runtime`, not on the Finbar application. This spec assumes the package stops at signal generation. Finbot keeps all bot-specific adapters: Hyperliquid market data/order gateways, dry-run/testnet/live branching, risk gates, persistence, reconciliation, account websocket handling, CLI/MCP control, and startup wiring. Strategy schema versioning remains independent from package semver.

## Non-Goals
- Importing the monolithic `finbar` package.
- Calling Finbar REST/MCP services at runtime.
- Moving Finbot live-trading adapters, repositories, risk gates, or exchange code into the shared package.
- Changing live-mode safety requirements.
- Silently enabling unsupported strategy schema versions or unsupported runtime package capabilities.
