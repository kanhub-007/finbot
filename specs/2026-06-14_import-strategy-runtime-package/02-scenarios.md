# Scenarios — Import Shared Strategy Runtime Package

Scenarios use Classical-school, black-box tests with in-memory fakes for streams, repositories, gateways, and market metadata.

---

### Scenario: Finbot starts with shared runtime package and no Finbar application dependency
**Priority:** Must  
**Slice:** 1

**Gherkin:**
  Given `finbar-strategy-runtime` is installed
  When Finbot validates and loads a supported YAML strategy
  Then Finbot uses the package parser/evaluator semantics and production code does not import the Finbar application

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| package_distribution | string | `finbar-strategy-runtime` | Installed dependency |
| package_import | string | `finbar_strategy_runtime` | Importable |
| strategy_path | string | target YAML fixture | Readable, schema `2.0` |
| mode | enum | `dry_run` | No exchange submission |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| target YAML parses and validates | Startup result valid/running |
| production code imports `finbar_strategy_runtime`, not `finbar` | Architecture test |
| no local Finbar path or REST/MCP service is required | Clean venv test without Finbar checkout |
| compatibility result includes package version and schema version | Inspect startup/capability result |

**Verify (Classical school, black-box):**
```python
runtime = create_runtime_with_fakes()
result = runtime.start_once_for_test(
    strategy_path=AMT_DIP,
    symbol="BTC",
    interval="1h",
    mode="dry_run",
)

assert result.status == "running"
assert result.strategy_name
assert result.compatibility_valid is True
assert result.supported_schema_version == "2.0"
```

**Also test:**
- Uninstall/remove local Finbar checkout -> Finbot tests still pass.
- Production code has zero `import finbar` occurrences.
- Missing shared runtime package -> startup/import error is clear.
- Unsupported package capability -> startup rejected before subscription.

---

### Scenario: Copied strategy runtime code is replaced by package adapters
**Priority:** Must  
**Slice:** 1

**Gherkin:**
  Given Finbot has copied strategy runtime modules
  When the shared runtime package is adopted
  Then Finbot keeps only thin adapters/factories/mappers needed for its own domain and removes duplicate parser/evaluator/indicator logic

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| copied_runtime_path | path | `finbot/infrastructure/strategy/` | Contains copied Finbar runtime subset |
| package_api | module | `finbar_strategy_runtime.*` | Stable public imports |
| adapter_scope | enum | loader/evaluator/indicator mapper | Finbot-owned only |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| parser/evaluator/risk/indicator semantics come from package | Behaviour tests pass after deleting copies |
| Finbot adapters convert package signals to `SignalDecision`/order planning inputs | Inspect public processing result |
| Hyperliquid, SQLite, risk gates, and live mode code remain in Finbot | Architecture tests |
| no package code imports Finbot | Package architecture/contract tests |

**Verify (Classical school, black-box):**
```python
loader = SharedRuntimeStrategyDefinitionLoader()
definition = loader.load_from_file(AMT_DIP)
factory = SharedRuntimeStrategyEvaluatorFactory()
evaluator = factory.create(definition, symbol="BTC", interval="1h", strategy_hash="abc")

decision = evaluator.evaluate(enriched_bar_that_triggers_entry, flat_position)

assert decision.action.value in {"hold", "long_entry", "short_entry"}
assert decision.symbol == "BTC"
```

**Also test:**
- Existing `RuleBasedStrategyEvaluatorFactory` behaviour is preserved through adapter.
- Package `SignalResult` maps to Finbot `SignalDecision` without exchange details.
- Adapter rejects package results with unknown action values.
- Strategy hash/content hash remains deterministic across restarts.

---

### Scenario: Live runtime uses shared package until the submission boundary only
**Priority:** Must  
**Slice:** 2

**Gherkin:**
  Given a running dry-run/testnet/live Finbot session
  When a closed candle is processed
  Then shared runtime handles strategy parsing/enrichment/evaluation, and Finbot handles warmup, enrichment validation, signal persistence, risk gates, idempotency, and exchange submission branch

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| closed_candle | dict | OHLCV candle | Closed and new timestamp |
| warmup_bars | list[dict] | historical bars | Enough for required indicators |
| mode | enum | dry_run/testnet/live | Safety gates apply |
| required_columns | set[string] | `atr`, `vp_vah`, `vp_val` | Derived from package strategy definition |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| strategy evaluation is skipped until Finbot warmup/enrichment validation passes | Processing result |
| dry-run never submits orders | Fake gateway submitted count remains 0 |
| testnet/live submission uses Finbot `ExchangeGateway` only | Repository/gateway state |
| duplicate signal prevention remains Finbot-owned | Same repository rejects duplicate |

**Verify (Classical school, black-box):**
```python
repo = InMemoryBotStateRepository()
exchange = DryRunExchangeGateway()
runtime = create_runtime_with_shared_package_and_fakes(repository=repo, exchange=exchange)

runtime.start_once_for_test(strategy_path=AMT_DIP, symbol="BTC", interval="1h", mode="dry_run")
result = runtime.process_closed_candle(closed_candle_that_triggers_long_entry)

assert result.enrichment_valid is True
assert repo.last_signal() is not None
assert exchange.submitted_order_count == 0
```

**Also test:**
- Missing required enriched column -> Finbot blocks before evaluation.
- `NaN` required indicator -> Finbot blocks before evaluation.
- Duplicate closed candle -> no duplicate order intent.
- Live blockers prevent websocket subscription before package evaluation is relevant.

---

### Scenario: Finbot compatibility check uses package capabilities and schema versions
**Priority:** Must  
**Slice:** 2

**Gherkin:**
  Given a strategy definition and installed runtime package
  When Finbot performs compatibility validation
  Then it accepts only supported schema versions, operators, indicators, feature types, and risk modes before starting live data subscription

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| strategy_schema_version | string | `2.0` | Must be in package supported schemas |
| package_version | semver | `0.1.0` | Used for diagnostics, not schema matching |
| required_indicators | list[string] | `atr`, `vp_vah` | Must be in capability catalog |
| runtime_mode | enum | dry_run/testnet/live | Live may require stricter checks |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| unsupported schema version rejected | Compatibility result blockers |
| unsupported live-only feature rejected before stream subscription | Fake stream subscription count 0 |
| result reports package version and supported schema versions | Inspect compatibility result |
| schema version is not inferred from package semver | Test package `0.2.0` supports schema `2.0` |

**Verify (Classical school, black-box):**
```python
compat = StrategyCompatibilityService(runtime_capabilities).check(strategy_definition, mode="live")

assert compat.valid is True
assert "2.0" in compat.supported_schema_versions
assert compat.runtime_package_version
```

**Also test:**
- Strategy schema `3.0` rejected until supported.
- Known schema with unsupported indicator rejected.
- Missing stop loss in live mode rejected by Finbot policy, not package parser.
- Package capability report is persisted in startup audit.

---

### Scenario: Finbot package migration preserves existing live-runtime behaviour
**Priority:** Should  
**Slice:** 3

**Gherkin:**
  Given Finbot currently passes live YAML runtime scenarios with copied code
  When copied code is replaced by package-backed adapters
  Then existing runtime scenarios still pass and parity tests against Finbar become package contract tests

**Input table:**
| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| existing_spec | path | `2026-06-12_live-yaml-trading-runtime` | Scenarios remain source of truth |
| fixtures | YAML strategies | `amt_dip_buyer_final.yaml`, `amt_v2_vol_filter.yaml` | Must start in dry-run |
| runtime_mode | enum | dry_run/testnet/live | Existing safety rules apply |

**Expected output / state change:**
| Assertion | How to verify |
|-----------|---------------|
| all Slice 1 live runtime tests still pass | `pytest tests` |
| placeholder `FinbarStrategyEvaluator` is removed or unused | Behaviour: triggered bar does not always HOLD |
| optional parity tests no longer require importing monolithic Finbar | Package contract tests |
| copied runtime inventory doc is updated as deprecated/removed | Docs check |

**Verify (Classical school, black-box):**
```python
result = runtime.start_once_for_test(strategy_path=AMT_V2, symbol="BTC", interval="1h", mode="dry_run")
fake_stream.emit_closed_candle(closed_candle_that_triggers_known_entry)

assert result.status == "running"
assert repo.last_signal().action.value != "hold"
```

**Also test:**
- Both target fixtures start successfully.
- Replay/dry-run results are unchanged for fixture bars.
- Testnet order submission still uses Finbot `cloid` and gateway.
- Live mode still requires durable persistence and reconciliation.
