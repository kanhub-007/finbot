# Scenarios — Import Shared Strategy Runtime Package

Scenarios use Classical-school, black-box tests with in-memory fakes for
streams, repositories, and gateways. They assert on **outcomes** (returned
values / observable state), never on which internal methods were called.

Real class names referenced below are the post-migration names defined in
`03-domain.md`. Fixture strategy files live in `tests/fixtures/strategies/`
(e.g. `amt_dip_buyer_final.yaml`, `amt_v2_vol_filter.yaml`).

---

### Scenario: Finbot runs on the shared package with no Finbar application dependency
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given `finbar-strategy-runtime` is installed
  When Finbot loads a supported YAML strategy and evaluates one closed candle
  Then Finbot uses the package parser/evaluator/indicator semantics and production code does not import the monolithic `finbar` application

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| package_import | string | `finbar_strategy_runtime` | Importable, version `0.1.0` |
| strategy_path | path | `tests/fixtures/strategies/amt_dip_buyer_final.yaml` | Readable, schema `2.0` |
| mode | enum | `dry_run` | No exchange submission |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| YAML parses and validates | `YamlStrategyDefinitionLoader().load_from_file(path)` returns a `StrategyDefinition` |
| A triggered bar produces a non-HOLD `SignalDecision` | Inspect `evaluator.evaluate(bar, position).action` |
| production code has zero `import finbar` / `from finbar ` | Architecture test `TestNoFinbarInProductionCode` |
| `finbar_strategy_runtime` is a declared dependency | `grep finbar-strategy-runtime pyproject.toml` |

**Verify (Classical school, black-box):**
```python
from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
    SharedRuntimeStrategyEvaluatorFactory,
)
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

definition = YamlStrategyDefinitionLoader().load_from_file(AMT_DIP)
evaluator = SharedRuntimeStrategyEvaluatorFactory().create(
    definition, symbol="BTC", interval="1h", strategy_hash="abc"
)

decision = evaluator.evaluate(enriched_bar_that_triggers_long_entry, flat_position)

assert decision.action.value in {"long_entry", "short_entry"}
assert decision.symbol == "BTC"
assert decision.interval == "1h"
assert decision.strategy_hash == "abc"
```

**Also test:**
- Remove the local Finbar checkout from the environment -> Finbot tests still pass (the package is the only Finbar-derived dependency).
- Missing package -> import error at startup is clear.
- Package import appears in `infrastructure/` and `startup/` only (plus `core/domain` for the pure `domain.entities`/`domain.interfaces` subpackages) -> architecture test.

---

### Scenario: Copied strategy runtime code is replaced by the package
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given Finbot has copied strategy runtime modules and copied strategy domain entities
  When the shared runtime package is adopted
  Then the copied modules and entities are deleted, and Finbot keeps only the thin evaluator adapter that maps the package `SignalResult` to a Finbot `SignalDecision`

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| copied_runtime_path | path | `finbot/infrastructure/strategy/` | Parser/evaluator/indicator copies |
| copied_entity_path | path | `finbot/core/domain/entities/strategy_definition.py` (+ ~19 siblings) | Copied domain entities |
| package_api | module | `finbar_strategy_runtime.*` | Used directly for strategy domain + runtime |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| No copied parser/evaluator/indicator/strategy files remain | `git status` / file listing |
| Copied strategy domain entities are gone, replaced by package imports | `rg "class StrategyDefinition" finbot` returns zero hits |
| `SignalResult` (package) -> `SignalDecision` (Finbot) mapping lives in one adapter | Inspect `SharedRuntimeStrategyEvaluator` |
| Finbot live-trading code (exchange, repos, risk gates, order planning) is untouched | Architecture tests still pass |

**Verify (Classical school, black-box):**
```python
# The adapter is the ONLY place that knows about both SignalResult and SignalDecision.
from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator import (
    SharedRuntimeStrategyEvaluator,
)

# A package HOLD maps to a Finbot HOLD with live idempotency fields filled in.
decision = evaluator.evaluate(bar_with_no_signal, flat_position)
assert decision.action.value == "hold"
assert decision.signal_key  # symbol/interval/ts/hash all populated
```

**Also test:**
- Unknown `SignalResult.action` value (not buy/sell/hold) -> adapter raises a clear `ValueError`.
- Exit signal resolves to `LONG_EXIT` vs `SHORT_EXIT` using the **current position direction** (the package `SignalResult` alone is ambiguous on exit side).
- Strategy content hash stays deterministic across restarts (unchanged, Finbot-owned `_hash_strategy_file`).

---

### Scenario: Live runtime uses the package only up to the signal boundary
**Priority:** Must
**Slice:** 2

**Gherkin:**
  Given a running dry-run/testnet/live Finbot session
  When a closed candle is processed
  Then the package handles parsing/indicators/evaluation, and Finbot handles warmup, enrichment validation, signal persistence, risk gates, idempotency, and the exchange submission branch

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| closed_candle | dict | OHLCV candle | Closed and new timestamp |
| warmup_bars | list[dict] | historical bars | Enough for required indicators |
| mode | enum | dry_run/testnet/live | Safety gates apply |
| required_columns | set[str] | `atr`, `vp_vah`, `vp_val` | Taken from the package validation result, not hand-maintained |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Evaluation is skipped until Finbot warmup + enrichment validation pass | `CandleProcessingResult.enrichment_valid is False` during warmup |
| Dry-run never submits orders | Fake gateway `submitted_order_count == 0` |
| Testnet/live submission uses the Finbot `ExchangeGateway` only | Repository/gateway state |
| Duplicate signal prevention stays Finbot-owned | Same repository rejects a duplicate `signal_key` |

**Verify (Classical school, black-box):**
```python
repo = InMemoryBotStateRepository()
exchange = DryRunExchangeGateway()
runtime = create_live_runtime_with_fakes(repository=repo, exchange=exchange)

runtime.start(strategy_path=AMT_DIP, symbol="BTC", interval="1h")
result = runtime.process_closed_candle(closed_candle_that_triggers_long_entry)

assert result.enrichment_valid is True
assert repo.last_signal() is not None
assert exchange.submitted_order_count == 0  # dry-run
```

**Also test:**
- Missing required enriched column -> Finbot blocks before evaluation (`EnrichmentValidator`).
- `NaN` in a required indicator -> Finbot blocks before evaluation.
- Duplicate closed candle -> no duplicate order intent (`DuplicateSignalGate`).

---

### Scenario: Required indicator columns come from the package, not a hand-maintained list
**Priority:** Must
**Slice:** 2

> This scenario replaces a latent bug: the current factory derives required
> columns as `{ind.name for ind in definition.indicators}` (the strategy-local
> **alias**), which is wrong — the enrichment validator needs the **concrete
> column** (e.g. `sma_20`, `atr`). The package's parser already returns the
> correct list as `StrategyValidationResult.required_columns`.

**Gherkin:**
  Given a parsed strategy definition
  When Finbot wires the live runtime
  Then the set of required enriched columns is read from the package validation result's `required_columns` field

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| strategy_path | path | AMT dip buyer fixture | Uses aliases like `atr`, `vp_vah` |
| required_columns | list[str] | `["atr","vp_vah","vp_val",...]` | From package, concrete column names |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| `required_columns` contains concrete names, not aliases | Inspect the runtime's `_required_columns` |
| A bar missing a concrete column is rejected before evaluation | `EnrichmentValidator` rejects |

**Verify (Classical school, black-box):**
```python
from finbar_strategy_runtime.parser.strategy_definition_parser import (
    StrategyDefinitionParser,
)
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

# The loader must surface the package's required_columns.
loader = YamlStrategyDefinitionLoader()
definition = loader.load_from_file(AMT_DIP)
# (Loader API: see 03-domain.md — it exposes the package validation result so
#  required_columns is available to the factory without re-parsing.)
assert "vp_vah" in loader.last_required_columns()
```

**Also test:**
- Adding a new indicator to the strategy automatically appears in `required_columns` (no Finbot code change).
- Dynamic-period indicators (e.g. `sma_37`) produce the right concrete column.

---

### Scenario: Finbot compatibility check uses package capabilities and Finbot live policy
**Priority:** Must
**Slice:** 2

**Gherkin:**
  Given a strategy definition and the installed runtime package
  When Finbot performs compatibility validation
  Then it accepts only supported schema versions and catalogued indicators/operators, and applies Finbot-specific live policy (e.g. "no stop loss in live mode = reject") on top

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| strategy_schema_version | string | `2.0` | Must be in package supported schemas |
| package_version | semver | `0.1.0` | Diagnostics only, never used for schema matching |
| required_indicators | list[str] | `atr`, `vp_vah` | Must be in the package capability catalog |
| runtime_mode | enum | dry_run/testnet/live | Live applies stricter policy |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| Unsupported schema version rejected | `compatibility()` reports `parse: error` |
| Unknown indicator rejected with its name | Compatibility result lists the indicator |
| Missing stop loss in `live` rejected by **Finbot policy**, not the package parser | Compatibility result lists `stop_loss: missing` in live mode |
| Result reports package name/version + supported schema versions | Inspect compatibility result |

**Verify (Classical school, black-box):**
```python
from finbot.core.application.use_cases.validate_strategy_definition import (
    ValidateStrategyUseCase,
)
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

validator = ValidateStrategyUseCase(loader=YamlStrategyDefinitionLoader())
result = validator.compatibility(
    ValidateStrategyRequest(strategy_path=AMT_DIP, strategy_content=CONTENT)
)

# Schema 2.0 parses cleanly; live mode adds Finbot policy checks on top.
assert "parse" in result.modes["live"]
```

**Also test:**
- Strategy with `schema_version: "3.0"` -> rejected (package enforces `2.0`).
- Strategy with an indicator not in the package catalog -> rejected with the name.
- Package `0.2.0` still supporting schema `2.0` -> compatible (schema version is independent of package semver).

---

### Scenario: Migration preserves existing live-runtime behaviour
**Priority:** Should
**Slice:** 3

**Gherkin:**
  Given Finbot currently passes live YAML runtime scenarios with copied code
  When copied code is replaced by package-backed adapters
  Then existing runtime scenarios still pass and the optional parity test (which imported the monolithic Finbar app) is removed — parity is now **structural** because both sides use the same package

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| existing_spec | path | `specs/2026-06-12_live-yaml-trading-runtime` | Scenarios remain source of truth |
| fixtures | YAML strategies | `amt_dip_buyer_final.yaml`, `amt_v2_vol_filter.yaml` | Must start in dry-run |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| All Slice 1/2 live runtime tests still pass | `pytest tests` green |
| `tests/test_parity/test_finbar_strategy_parity.py` is deleted | File listing |
| Placeholder `FinbarStrategyEvaluator` is deleted | `rg FinbarStrategyEvaluator finbot` returns zero hits |

**Verify (Classical school, black-box):**
```python
result = runtime.start(strategy_path=AMT_V2, symbol="BTC", interval="1h")
fake_stream.emit_closed_candle(closed_candle_that_triggers_known_entry)

assert result.status == "running"
assert repo.last_signal().action.value != "hold"
```

**Also test:**
- Both target fixtures start successfully in dry-run.
- Replay/dry-run results are unchanged for fixture bars.
- Testnet order submission still uses Finbot `cloid` and the `ExchangeGateway`.
- Live mode still requires durable persistence and startup reconciliation.
