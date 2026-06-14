# Implementation Guide — Import Shared Strategy Runtime Package

## Step 1: Add package dependency without adding Finbar app dependency
**File:** `Github/finbot/pyproject.toml`

Add:
```toml
"finbar-strategy-runtime[pandas,yaml]>=0.1.0,<0.2.0"
```

Do not add `finbar` as a dependency. During local development, use editable install tooling outside committed production dependency metadata if necessary.

**Verify:** `python -c "import finbar_strategy_runtime; import finbot"` in a clean venv without `Github/finbar` on `PYTHONPATH`.

**Common mistake:** Depending on the local monolithic Finbar checkout to make tests pass.

---

## Step 2: Add package-backed adapters
**Files:**
- `finbot/infrastructure/strategy/shared_runtime_strategy_definition_loader.py`
- `finbot/infrastructure/strategy/shared_runtime_strategy_evaluator.py`
- `finbot/infrastructure/strategy/shared_runtime_strategy_evaluator_factory.py`
- `finbot/infrastructure/strategy/shared_runtime_indicator_calculator.py`

Adapters implement existing Finbot domain interfaces and map package outputs to Finbot DTOs/entities.

**Verify:** existing loader/evaluator/indicator tests pass using only public Finbot interfaces.

**Common mistake:** Importing package types directly throughout live runtime use cases instead of hiding them behind Finbot interfaces where useful.

---

## Step 3: Replace copied runtime wiring in startup
**File:** `finbot/startup/service_factory.py`

Wire package-backed implementations into existing use cases:
- strategy loader;
- evaluator factory;
- indicator calculator;
- compatibility/capability provider.

Keep exchange gateways, market streams, repositories, risk gates, live guards, account event handlers, and order planners wired to Finbot implementations.

**Verify:** `pytest tests/test_application tests/test_infrastructure tests/test_architecture`.

**Common mistake:** Moving Finbot risk gates or Hyperliquid adapters into the shared runtime package.

---

## Step 4: Remove or deprecate copied runtime modules
**File:** `finbot/infrastructure/strategy/`

After adapters are green, delete copied parser/evaluator/risk/indicator runtime files or leave compatibility shims that import from package-backed adapters for one release only. Update `docs/FINBAR_RUNTIME_COPY.md` to state the copy inventory is superseded.

**Verify:** architecture test fails if deleted copied modules are imported by production code.

**Common mistake:** Keeping two active implementations and selecting one by config.

---

## Step 5: Keep Finbot adapters and live concerns in Finbot
**Files:** existing Finbot adapter/repository/risk/live runtime files

This step reflects the boundary decision: Finbot-specific behaviour remains local.

Do not move these into the package:
- Hyperliquid gateways and streams;
- dry-run/testnet/live submission branching;
- `cloid` generation and duplicate prevention;
- bot state repository and SQLite migrations;
- risk gates;
- live mode guard;
- reconciliation and account websocket processing;
- CLI/MCP bot control.

**Verify:** `rg "hyperliquid|ExchangeGateway|BotStateRepository|LiveModeGuard" <shared package>` returns no package production hits.

**Common mistake:** Asking the package to know whether a signal is safe to trade live. It only knows strategy semantics.

---

## Step 6: Enforce package/schema version compatibility
**Files:**
- `finbot/core/domain/dto/strategy_compatibility_result.py`
- `finbot/infrastructure/strategy/strategy_capability_service.py` or replacement adapter

Compatibility output must include:
- runtime package name/version;
- supported strategy schema versions;
- active strategy schema version;
- unsupported indicators/operators/features/risk modes;
- Finbot live-mode policy blockers.

**Verify:** tests prove package version `0.2.0` can still support schema `2.0`, and schema `3.0` is rejected unless capability says supported.

**Common mistake:** Treating package semver as strategy schema version.

---

## Step 7: Run live runtime scenarios unchanged
**Files:** existing tests for `2026-06-12_live-yaml-trading-runtime`

Run the existing live YAML runtime spec tests. The expected runtime behaviour should not change except that parity is provided by the shared package contract instead of copied code.

**Verify:** `pytest tests`.

**Common mistake:** Updating tests to expect implementation classes instead of public outcomes.
