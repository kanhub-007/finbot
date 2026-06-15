# Implementation Guide — Import Shared Strategy Runtime Package

This guide is ordered so each step compiles/imports cleanly before the next.
Run the **Verify** command after every step. All paths are relative to the
Finbot repo root (`C:/HAL/Github/finbot`) unless marked otherwise.

> The package lives at `C:/HAL/Github/finbar/packages/strategy-runtime/` and is
> imported as `finbar_strategy_runtime` (v0.1.0). It is already installed
> editable into Finbot's venv, so you do **not** need to publish to PyPI.

---

## Step 0: Confirm the baseline
**Verify (run, expect all green or pre-existing skips):**
```bash
cd C:/HAL/Github/finbot
python -c "import finbar_strategy_runtime as r; print('pkg', r.__version__)"
ruff check finbot tests
python -m pytest tests -q
```
If the suite already has failures unrelated to this work, note them before
starting so you can tell your changes apart. (Known environment note:
`tests/test_infrastructure/test_indicator_registry.py` currently errors on
collection if `pandas_ta` is missing — fix the env with
`pip install -e ".[dev]"` from the finbot repo, or ignore it for now; this spec
deletes that test file in Step 6.)

**Common mistake:** starting edits before confirming the package imports. If
`import finbar_strategy_runtime` fails, install it editable first:
`pip install -e C:/HAL/Github/finbar/packages/strategy-runtime[pandas,yaml]`.

---

## Step 1: Declare the package dependency
**File:** `pyproject.toml`

Add `finbar-strategy-runtime` to the `dependencies` list (keep `[pandas,yaml]`
extras — the indicator engine needs pandas/numpy/pandas-ta and the parser needs
PyYAML):

```toml
dependencies = [
    "finbar-strategy-runtime[pandas,yaml]>=0.1.0,<0.2.0",
    "hyperliquid-python-sdk>=0.10.0",
    "numpy>=1.26.0",
    "pandas>=2.0.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0.0",
    "sqlalchemy>=2.0.0",
]
```

Do **NOT** add `finbar` (the app). The package depends on it for nothing.

**Verify:**
```bash
pip install -e ".[dev]"
python -c "import finbar_strategy_runtime, finbot; print('ok')"
```

**Common mistake:** adding a path dependency on the monolithic Finbar checkout.

---

## Step 2: Re-point the domain interfaces to the package entities
These three Finbot interfaces currently reference Finbot's **copied** entities.
Change them to reference the package entities. (This is allowed: package
`domain.entities`/`domain.interfaces` are pure — see `03-domain.md` boundary
table.)

**File `finbot/core/domain/interfaces/strategy_definition_loader.py`** — change the entity import:
```python
# before
from finbot.core.domain.entities.strategy_definition import StrategyDefinition
# after
from finbar_strategy_runtime.domain.entities.strategy_definition import StrategyDefinition
```

**File `finbot/core/domain/interfaces/strategy_evaluator_factory.py`** — same change:
```python
# before
from finbot.core.domain.entities.strategy_definition import StrategyDefinition
# after
from finbar_strategy_runtime.domain.entities.strategy_definition import StrategyDefinition
```

**File `finbot/core/domain/interfaces/strategy_definition_parser.py`** — if it
references a copied entity/result type, re-point to the package equivalents
(`finbar_strategy_runtime.domain.entities.strategy_validation_result.StrategyValidationResult`).
Inspect the file; if it is now unused after Step 5 (no Finbot code implements
it), delete it instead.

**Verify:** `python -c "import finbot.core.domain.interfaces.strategy_definition_loader, finbot.core.domain.interfaces.strategy_evaluator_factory"`

**Common mistake:** editing the interfaces but leaving a stale
`finbot.core.domain.entities.strategy_definition` import elsewhere. Step 3/5
remove those.

---

## Step 3: Create the three new infrastructure adapters
Create these files. Each is short — one real delegation each.

### File `finbot/infrastructure/adapters/shared_runtime_strategy_evaluator.py` (new)
```python
"""Adapter: package TradingStrategy -> Finbot StrategyEvaluator."""

from typing import Any

from finbar_strategy_runtime.domain.entities.signal_result import SignalResult
from finbar_strategy_runtime.domain.interfaces.trading_strategy import TradingStrategy
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator


class SharedRuntimeStrategyEvaluator(StrategyEvaluator):
    """Wrap a package TradingStrategy and emit a Finbot SignalDecision."""

    def __init__(
        self,
        strategy: TradingStrategy,
        *,
        symbol: str,
        interval: str,
        strategy_hash: str,
    ) -> None:
        self._strategy = strategy
        self._symbol = symbol
        self._interval = interval
        self._strategy_hash = strategy_hash
        self._candle_timestamp: int = 0

    def evaluate(
        self,
        enriched_bar: dict[str, Any],
        position: PositionSnapshot,
    ) -> SignalDecision:
        """Evaluate one enriched closed bar and return a typed signal."""
        self._candle_timestamp = int(
            enriched_bar.get("candle_timestamp", self._candle_timestamp + 1)
        )

        package_position = {
            "size": float(position.size),
            "direction": _direction_str(position.direction),
        }
        result = self._strategy.on_bar(enriched_bar, package_position)
        action = _map_signal(result, position.direction)

        return SignalDecision(
            action=action,
            symbol=self._symbol,
            interval=self._interval,
            candle_timestamp=self._candle_timestamp,
            strategy_hash=self._strategy_hash,
            confidence=result.confidence,
            stop_price=result.stop_price or None,
            target_price=result.target_price or None,
        )

    def reset(self) -> None:
        """Reset crossover state for a new session."""
        self._strategy.on_reset()
        self._candle_timestamp = 0


def _direction_str(direction: PositionDirection) -> str:
    """Finbot PositionDirection -> package position dict direction."""
    if direction == PositionDirection.LONG:
        return "long"
    if direction == PositionDirection.SHORT:
        return "short"
    return ""  # FLAT


def _map_signal(result: SignalResult, position_direction: PositionDirection) -> SignalAction:
    """Map package SignalResult (+ current side) -> Finbot SignalAction."""
    action = result.action
    direction = result.direction

    if action == "hold":
        return SignalAction.HOLD
    if action == "buy" and direction == "long":
        return SignalAction.LONG_ENTRY
    if action == "sell" and direction == "short":
        return SignalAction.SHORT_ENTRY
    if direction == "exit":
        # The package result does not say which side is being exited.
        if position_direction == PositionDirection.LONG:
            return SignalAction.LONG_EXIT
        if position_direction == PositionDirection.SHORT:
            return SignalAction.SHORT_EXIT
    raise ValueError(
        f"Unmappable package signal: action={action!r} direction={direction!r}"
    )
```

### File `finbot/infrastructure/adapters/shared_runtime_strategy_evaluator_factory.py` (new)
```python
"""Factory: package StrategyDefinition -> SharedRuntimeStrategyEvaluator."""

from finbar_strategy_runtime.domain.entities.strategy_definition import (
    StrategyDefinition,
)
from finbar_strategy_runtime.domain.interfaces.trading_strategy import TradingStrategy
from finbar_strategy_runtime.evaluation.strategy_definition_factory import (
    StrategyDefinitionFactory,
)
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator
from finbot.core.domain.interfaces.strategy_evaluator_factory import (
    StrategyEvaluatorFactory,
)
from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator import (
    SharedRuntimeStrategyEvaluator,
)


class SharedRuntimeStrategyEvaluatorFactory(StrategyEvaluatorFactory):
    """Create SharedRuntimeStrategyEvaluator instances via the package factory."""

    def __init__(self, package_factory: StrategyDefinitionFactory | None = None) -> None:
        self._package_factory = package_factory or StrategyDefinitionFactory()

    def create(
        self,
        definition: StrategyDefinition,
        symbol: str,
        interval: str,
        strategy_hash: str,
    ) -> StrategyEvaluator:
        strategy: TradingStrategy = self._package_factory.create(definition)
        return SharedRuntimeStrategyEvaluator(
            strategy,
            symbol=symbol,
            interval=interval,
            strategy_hash=strategy_hash,
        )
```

### File `finbot/infrastructure/strategy/shared_runtime_indicator_calculator.py` (new)
```python
"""Adapter: package PandasTaIndicatorCalculator -> Finbot IndicatorCalculator."""

from typing import Any

from finbar_strategy_runtime.indicators.pandas_ta_indicator_calculator import (
    PandasTaIndicatorCalculator as _PackageCalculator,
)
from finbot.core.domain.interfaces.indicator_calculator import IndicatorCalculator


class SharedRuntimeIndicatorCalculator(IndicatorCalculator):
    """Thin delegation to the shared package indicator engine."""

    def __init__(self) -> None:
        self._calc = _PackageCalculator()

    def calculate(self, df: Any, indicators: list[str]) -> Any:
        """Apply requested indicators and return the enriched frame."""
        return self._calc.calculate(df, indicators)
```

**Verify:**
```bash
ruff check finbot/infrastructure/adapters/shared_runtime_strategy_evaluator.py finbot/infrastructure/adapters/shared_runtime_strategy_evaluator_factory.py finbot/infrastructure/strategy/shared_runtime_indicator_calculator.py
python -c "from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import SharedRuntimeStrategyEvaluatorFactory; print('ok')"
```

**Common mistake:** putting the package `TradingStrategy`/`StrategyDefinition`
types in the adapter's **public** Finbot-facing signature. The adapter's public
method signature is the Finbot interface only; package types appear only in the
implementation (acceptable — the adapter lives in infrastructure).

---

## Step 4: Re-point the loader to the package parser and surface `required_columns`
**File `finbot/infrastructure/strategy/yaml_strategy_definition_loader.py`**

Swap the parser import and retain the last validation result so callers can
read `required_columns` (the package computes the correct concrete columns;
the old factory's `{ind.name ...}` alias-based derivation was a bug — see
Scenario in `02-scenarios.md`).

```python
# before
from finbot.infrastructure.strategy.strategy_definition_parser import (
    StrategyDefinitionParser,
)
# after
from finbar_strategy_runtime.parser.strategy_definition_parser import (
    StrategyDefinitionParser,
)
from finbar_strategy_runtime.domain.entities.strategy_validation_result import (
    StrategyValidationResult,
)
from finbar_strategy_runtime.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.entities.strategy_load_error import StrategyLoadError
from finbot.core.domain.interfaces.strategy_definition_loader import (
    StrategyDefinitionLoader,
)
```

In `load_from_text`, keep the `StrategyValidationResult` on the instance and add
accessors:
```python
    def __init__(self, parser: StrategyDefinitionParser | None = None):
        self._parser = parser or StrategyDefinitionParser()
        self._last_result: StrategyValidationResult | None = None

    def load_from_text(self, content: str) -> StrategyDefinition:
        result = self._parser.parse(content)
        self._last_result = result
        if not result.valid:
            messages = "; ".join(e.message for e in result.errors)
            raise StrategyLoadError(f"Strategy validation failed: {messages}")
        if result.definition is None:
            raise StrategyLoadError("Strategy validation passed but no definition returned")
        return result.definition

    def last_required_columns(self) -> list[str]:
        """Concrete enriched columns required by the last-loaded strategy."""
        return list(self._last_result.required_columns) if self._last_result else []
```

**Verify:** `python -m pytest tests/test_infrastructure/test_yaml_strategy_definition_loader.py -q`

**Common mistake:** recomputing required columns from `definition.indicators`.
Use `result.required_columns`.

---

## Step 5: Re-wire the composition root
**File `finbot/startup/service_factory.py`**

Three substitutions:

1. In `create_live_trading_runtime_use_case(...)`, replace the evaluator wiring:
```python
# before
from finbot.infrastructure.adapters.rule_based_strategy_evaluator_factory import (
    RuleBasedStrategyEvaluatorFactory,
)
evaluator = RuleBasedStrategyEvaluatorFactory().create(...)
# after
from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
    SharedRuntimeStrategyEvaluatorFactory,
)
evaluator = SharedRuntimeStrategyEvaluatorFactory().create(...)
```

2. In the same function, replace the indicator calculator and required-columns derivation:
```python
# before
from finbot.infrastructure.strategy.pandas_ta_indicator_calculator import (
    PandasTaIndicatorCalculator,
)
...
required_columns = {ind.name for ind in definition.indicators}  # BUG: aliases
# after
from finbot.infrastructure.strategy.shared_runtime_indicator_calculator import (
    SharedRuntimeIndicatorCalculator,
)
...
required_columns = set(loader.last_required_columns())
```

3. In `create_replay_strategy_use_case(...)`, switch the evaluator factory to
   `SharedRuntimeStrategyEvaluatorFactory` too (so replay uses the same engine).

4. Remove the `FinbarStrategyEvaluator` import/use from `create_run_bot_use_case(...)`
   — that path uses the placeholder. Either delete `create_run_bot_use_case` if
   it is dead, or rewire it through the live runtime like the others. Check
   callers (`rg create_run_bot_use_case`) before deleting.

**Verify:**
```bash
ruff check finbot/startup/service_factory.py
python -m pytest tests/test_startup/test_service_factory.py tests/test_application/test_live_trading_runtime.py -q
```

**Common mistake:** wiring the package evaluator into the order-submission
path. The adapter stops at signal generation; everything after is Finbot.

---

## Step 6: Delete the copied code
Delete the files below. They are now unreferenced after Steps 2–5. Delete in
this order and re-run `ruff check` + `pytest` after each group so a missed
import surfaces immediately.

### 6a. Copied strategy runtime modules — delete the whole directory's copied subset
Delete from `finbot/infrastructure/strategy/`:
```
condition_evaluator.py
description_visitor.py
feature_input_column_collector.py
indicator_registry.py
indicators/                       (entire directory)
json_risk_price_calculator.py
json_rule_based_strategy.py
max_condition_depth_limit_rule.py
max_features_limit_rule.py
max_indicators_limit_rule.py
max_parameters_limit_rule.py
no_exit_warning_rule.py
no_stop_warning_rule.py
pandas_signal_calculator.py
pandas_strategy_feature_calculator.py
pandas_formula_feature_calculator.py
pandas_ta_indicator_calculator.py
required_column_collector.py
serialize_group_visitor.py
strategy_capability_service.py
strategy_condition_group_parser.py
strategy_condition_parser.py
strategy_definition_parse_helpers.py
strategy_definition_parser.py
strategy_definition_serializer.py
strategy_feature_resolver.py
strategy_indicator_catalog.py
strategy_indicator_resolver.py
strategy_limit_rule.py
strategy_limit_rules.py
strategy_operand_parser.py
strategy_parameter_resolver.py
strategy_risk_resolver.py
strategy_schema_provider.py
strategy_timeframe_resolver.py
strategy_warning_rule.py
strategy_warning_rules.py
```

### 6b. Old evaluator adapters — delete
```
finbot/infrastructure/adapters/rule_based_strategy_evaluator.py
finbot/infrastructure/adapters/rule_based_strategy_evaluator_factory.py
finbot/infrastructure/adapters/finbar_strategy_evaluator.py
```

### 6c. Copied strategy domain entities — delete
Delete from `finbot/core/domain/entities/`:
```
condition.py
condition_group.py
data_mode.py
feature_spec.py
formula_node.py
indicator_spec.py
informative_timeframe.py
interval.py            (only imported by the deleted strategy_timeframe_resolver.py)
operand.py
risk_spec.py
side_rules.py
signal_result.py       (the package SignalResult is used directly)
strategy_definition.py
strategy_kind.py
strategy_meta.py
strategy_parameter.py
strategy_validation_error.py
strategy_validation_result.py
timeframe_declaration.py
volume_profile_result.py
```
Then update `finbot/core/domain/entities/__init__.py`: remove every re-export
line that points at a deleted file. Keep the Finbot-owned re-exports
(`SignalAction`, `SignalDecision`, `PositionSnapshot`, `PositionDirection`,
`OrderIntent`, `OrderSide`, `OrderType`, `EnrichmentValidationResult`,
`SafetyValidation`, etc.). If a Finbot-owned module still needs a strategy
entity, import it from `finbar_strategy_runtime.domain.entities` at the call
site instead of via the package-less `__init__`.

### 6d. Copied interfaces — delete or re-point
Delete if now unused (check with `rg` first):
```
finbot/core/domain/interfaces/strategy_definition_parser.py   (Finbot no longer needs its own parser interface; the package one is used directly)
finbot/core/domain/interfaces/trading_strategy.py             (Finbot uses the package TradingStrategy directly)
finbot/core/domain/interfaces/risk_price_calculator.py        (package-internal now)
finbot/core/domain/interfaces/condition_tree_visitor.py       (package-internal now)
finbot/core/domain/interfaces/indicator_capability_provider.py (package-internal now)
```
Keep: `strategy_evaluator.py`, `strategy_evaluator_factory.py`,
`strategy_definition_loader.py`, `indicator_calculator.py`,
`strategy_validator.py`, `bar_frame_converter.py` (Finbot-shaped).

### 6e. Stale tests — delete
```
tests/test_parity/test_finbar_strategy_parity.py        (imports monolithic finbar; parity is now structural)
tests/test_infrastructure/test_condition_evaluator.py   (tests deleted evaluator; covered by package contract tests)
tests/test_infrastructure/test_json_risk_price_calculator.py (covered by package)
tests/test_infrastructure/test_indicator_registry.py    (tests deleted registry)
tests/test_infrastructure/test_pandas_indicator_engine.py (replace with a thin SharedRuntimeIndicatorCalculator smoke test, or delete)
tests/test_domain/test_strategy_entities.py             (tests deleted entities; owned by package now)
```
Update (don't delete):
- `tests/test_infrastructure/test_rule_based_strategy_evaluator.py` -> rename
  to `test_shared_runtime_strategy_evaluator.py` and re-point imports to the
  new adapter; keep the black-box signal-mapping assertions.
- `tests/test_infrastructure/test_yaml_strategy_definition_loader.py` -> keep,
  it still tests Finbot's loader (now backed by the package parser).

### 6f. Docs
Update `docs/FINBAR_RUNTIME_COPY.md`: replace its contents with a short notice
that the copy has been superseded by the `finbar-strategy-runtime` package and
point readers to this spec.

**Verify after all deletions:**
```bash
ruff check finbot tests
python -m pytest tests -q
# No production code should import any deleted module:
rg "from finbot.infrastructure.strategy.(strategy_definition_parser|condition_evaluator|json_rule_based_strategy|pandas_ta_indicator_calculator|strategy_indicator_catalog|strategy_capability_service)" finbot
rg "RuleBasedStrategyEvaluator|FinbarStrategyEvaluator" finbot
rg "class StrategyDefinition|class Condition\b|class Operand" finbot/core
```
All three `rg` commands must return **zero** hits.

**Common mistake:** leaving a copied module "just in case". That recreates the
drift surface. Delete it; the package is the single source.

---

## Step 7: Update the architecture tests
**File `tests/test_architecture/test_dependency_rules.py`**

1. `TestNoFinbarInProductionCode` — keep as-is (still bans `import finbar`).

2. `TestDomainLayerImports` / `TestApplicationLayerImports` — their `FORBIDDEN`
   set must NOT include `finbar_strategy_runtime`. It currently lists `finbar`,
   `hyperliquid`, `sqlalchemy`, `fastapi` (the top-level module names).
   `finbar_strategy_runtime` is a different top-level name, so it is already
   allowed at the *name* level. But you must add a **new** test that enforces
   the subpackage allowlist from `03-domain.md`:

```python
class TestPackageSubpackageAllowlist:
    """finbar_strategy_runtime.parser/evaluation/indicators are infrastructure-only."""

    _INFRA_ONLY = {"parser", "evaluation", "indicators"}

    @pytest.mark.parametrize("file_path", _walk_finbot_sources("core/domain") + _walk_finbot_sources("core/application"),
                             ids=...)
    def test_domain_and_application_do_not_import_infra_subpackages(self, file_path):
        for imp in _collect_imports(file_path).get("finbar_strategy_runtime", set()):
            parts = imp.split(".")
            if len(parts) >= 2 and parts[1] in self._INFRA_ONLY:
                pytest.fail(f"{file_path} imports package infra subpackage {imp}")
```

3. Add a positive test that the pure subpackages ARE importable in domain:
```python
def test_package_domain_entities_used_in_finbot_domain(self):
    # at least one file under core/domain imports finbar_strategy_runtime.domain.entities
    ...
```

4. `TestCopiedRuntimeModules` — delete this class (the copied modules are gone).

**Verify:** `python -m pytest tests/test_architecture/test_dependency_rules.py -q`

**Common mistake:** deleting `TestNoFinbarInProductionCode`. It must still ban
the monolithic `finbar` app.

---

## Step 8: Compatibility / capability wiring
**Files:** `finbot/core/application/use_cases/validate_strategy_definition.py`
and the compatibility DTO.

Two rules:
- **Indicator/operator/schema support** comes from the package. Replace the
  hand-maintained `_KNOWN_INDICATORS` set with a lookup against the package
  capability catalog (`finbar_strategy_runtime.parser.strategy_capability_service.StrategyCapabilityService().get_capabilities()["indicators"]`,
  or the `UnifiedMetricCatalog`). This removes a drift source: when the package
  adds an indicator, Finbot accepts it automatically.
- **Finbot live policy** stays Finbot-owned. "Missing stop loss in `live` mode =
  reject" is a Finbot safety rule, not a package parser rule. Keep
  `_check_sides` / `_check_risk` policy logic; just feed it package-provided
  capability data.

Optionally extend `StrategyCompatibilityResult`
(`finbot/core/domain/dto/strategy_compatibility_result.py`) to carry
`runtime_package_name` and `runtime_package_version` for audit/diagnostics.
Read the version from `finbar_strategy_runtime.__version__`.

**Verify:** `python -m pytest tests/test_application/test_validate_strategy_definition.py tests/test_presentation/test_validate_strategy_cli.py -q`

**Common mistake:** coupling schema version to package semver. They are independent.

---

## Step 9: Full suite + review
```bash
ruff check finbot tests
black finbot tests
python -m pytest tests -q
```
Then run the review commands from `AGENTS.md` (`/review_quality`,
`/review_logic`, `/review_security`, `/review_performance`, `/review_tests`)
across the changed scope, fix findings, re-run tests.

**Definition of Done:**
- [ ] `finbar-strategy-runtime[pandas,yaml]` declared in `pyproject.toml`; `finbar` not.
- [ ] Zero `import finbar` in production code; zero copied strategy modules/entities.
- [ ] The three new adapters exist and are wired in `service_factory.py`.
- [ ] `required_columns` comes from the package validation result.
- [ ] Architecture tests enforce the package subpackage allowlist.
- [ ] Dry-run default, live ack, reduce-only, reconciliation behaviour unchanged.
- [ ] `pytest tests` green.
