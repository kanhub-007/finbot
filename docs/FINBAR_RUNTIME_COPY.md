# Finbar Runtime Copy Inventory

This document inventories every Finbar source file needed by the Finbot live
trading runtime. The copy scope is the **strategy runtime subset** only: parser,
validator, condition evaluator, risk calculator, indicator/AMT math.

Do not copy Finbar REST/MCP/presentation, startup, SQL repositories, backtest
engine, optimization engine, job managers, or data fetchers.

When copying any file, rewrite imports from `finbar.*` to `finbot.*` and place
under the corresponding `finbot/` layer.

---

## Tier 1 — Core runtime (executed every bar)

These are the three infrastructure files that form the live strategy evaluation
engine. They must be copied exactly (with import rewrites).

| Finbar source | Finbot target | Needed for | Dependencies | Notes |
|---|---|---|---|---|
| `finbar/infrastructure/services/json_rule_based_strategy.py` | `finbot/infrastructure/strategy/json_rule_based_strategy.py` | Live strategy evaluation → `TradingStrategy.on_bar()` | `condition_evaluator`, `json_risk_price_calculator`, domain entities | Core runtime. Adapts `TradingStrategy` interface to `StrategyEvaluator`. |
| `finbar/infrastructure/services/condition_evaluator.py` | `finbot/infrastructure/strategy/condition_evaluator.py` | Evaluate nested condition trees against enriched bars | Domain entities only (`Condition`, `ConditionGroup`, `Operand`) | Pure evaluator — no external deps beyond stdlib |
| `finbar/infrastructure/services/json_risk_price_calculator.py` | `finbot/infrastructure/strategy/json_risk_price_calculator.py` | Calculate stop-loss and take-profit from `RiskSpec` | Domain entities only (`RiskSpec`) | Pure calculator — no external deps |

---

## Tier 2 — Domain entities needed by runtime

Entities that the Tier 1 files import. All are pure dataclasses/enums with no
framework dependencies.

| Finbar source | Finbot target | Needed for | Dependencies | Notes |
|---|---|---|---|---|
| `finbar/core/domain/entities/condition.py` | `finbot/core/domain/entities/condition.py` | Atomic condition in rule trees | `operand.py` | Frozen dataclass |
| `finbar/core/domain/entities/condition_group.py` | `finbot/core/domain/entities/condition_group.py` | Nested boolean tree nodes | `condition.py` | Frozen dataclass |
| `finbar/core/domain/entities/operand.py` | `finbot/core/domain/entities/operand.py` | Typed operand for conditions | None | Frozen dataclass |
| `finbar/core/domain/entities/risk_spec.py` | `finbot/core/domain/entities/risk_spec.py` | Risk settings for stop/target calc | None | Frozen dataclass |
| `finbar/core/domain/entities/side_rules.py` | `finbar/core/domain/entities/side_rules.py` | Entry/exit condition trees per side | `condition_group.py` | Frozen dataclass |
| `finbar/core/domain/entities/signal_result.py` | `finbar/core/domain/entities/signal_result.py` | Signal output from strategy evaluation | None | Mutable dataclass — maps to `SignalDecision` |
| `finbar/core/domain/entities/volume_profile_result.py` | `finbot/core/domain/entities/volume_profile_result.py` | VP computation result | None | Used by volume profile math |
| `finbar/core/domain/entities/strategy_definition.py` | `finbot/core/domain/entities/strategy_definition.py` | Root strategy entity after parsing | `indicator_spec`, `feature_spec`, `side_rules`, `risk_spec`, `strategy_parameter`, `timeframe_declaration` | Frozen dataclass |
| `finbar/core/domain/entities/strategy_parameter.py` | `finbot/core/domain/entities/strategy_parameter.py` | Parameter definitions | None | Used by parser |
| `finbar/core/domain/entities/timeframe_declaration.py` | `finbot/core/domain/entities/timeframe_declaration.py` | Timeframe declaration | `informative_timeframe.py` | Used by parser |
| `finbar/core/domain/entities/informative_timeframe.py` | `finbot/core/domain/entities/informative_timeframe.py` | Informative timeframe spec | None | Frozen dataclass |
| `finbar/core/domain/entities/indicator_spec.py` | `finbot/core/domain/entities/indicator_spec.py` | Indicator specification | None | Frozen dataclass |
| `finbar/core/domain/entities/feature_spec.py` | `finbot/core/domain/entities/feature_spec.py` | Feature specification | None | Frozen dataclass. Not needed by AMT strategies but required for full schema parsing. |
| `finbar/core/domain/entities/formula_node.py` | `finbot/core/domain/entities/formula_node.py` | Formula AST for derived features | None | Only if formula features are supported |
| `finbar/core/domain/entities/strategy_validation_error.py` | `finbot/core/domain/entities/strategy_validation_error.py` | Validation error DTO | None | Used by parser/validator |
| `finbar/core/domain/entities/strategy_validation_result.py` | `finbot/core/domain/entities/strategy_validation_result.py` | Validation result DTO | `strategy_definition.py`, `strategy_validation_error.py` | Used by parser |
| `finbar/core/domain/entities/strategy_meta.py` | `finbot/core/domain/entities/strategy_meta.py` | Strategy metadata for `TradingStrategy.meta()` | None | Required by `TradingStrategy` interface |
| `finbar/core/domain/entities/strategy_kind.py` | `finbot/core/domain/entities/strategy_kind.py` | Enum for strategy type | None | Needed if schema references `strategy_kind` |

---

## Tier 3 — Domain interfaces

| Finbar source | Finbot target | Needed for | Dependencies | Notes |
|---|---|---|---|---|
| `finbar/core/domain/interfaces/risk_price_calculator.py` | `finbot/core/domain/interfaces/risk_price_calculator.py` | Stop/target calculation interface | `risk_spec.py` | ABC |
| `finbar/core/domain/interfaces/trading_strategy.py` | `finbot/core/domain/interfaces/trading_strategy.py` | Strategy execution interface (`on_bar`, `meta`) | `signal_result.py`, `strategy_meta.py` | ABC — adapt to `StrategyEvaluator` in Finbot |
| `finbar/core/domain/interfaces/indicator_calculator.py` | `finbot/core/domain/interfaces/indicator_calculator.py` | Indicator computation interface | None | ABC — for `pandas_ta_indicator_calculator` |
| `finbar/core/domain/interfaces/indicator_capability_provider.py` | `finbot/core/domain/interfaces/indicator_capability_provider.py` | Indicator catalog interface | None | ABC — for parser resolver layer |
| `finbar/core/domain/interfaces/condition_tree_visitor.py` | `finbot/core/domain/interfaces/condition_tree_visitor.py` | Visitor pattern for condition trees | `condition_group.py`, `condition.py` | ABC — used by serializer/explainer |

---

## Tier 4 — Domain services (indicator/AMT math)

Pure math functions. No framework dependencies beyond `numpy`/`pandas`.

| Finbar source | Finbot target | Needed for | Dependencies | Notes |
|---|---|---|---|---|
| `finbar/core/domain/services/amt_signals.py` | `finbot/core/domain/services/amt_signals.py` | AMT rule signals (acceptance_into_value, above_value, etc.) | numpy, pandas | Required by both target strategies |
| `finbar/core/domain/services/auction_state.py` | `finbot/core/domain/services/auction_state.py` | Auction state classifiers (inside/above/below_value, value_area_width_pct, balance) | numpy, pandas | Required by both target strategies |
| `finbar/core/domain/services/volume_profile.py` | `finbot/core/domain/services/volume_profile.py` | Session/rolling volume profile (vp_vah, vp_val, vp_poc) | `_profile_utils.py`, `volume_profile_result.py`, numpy, pandas | Required by both target strategies |
| `finbar/core/domain/services/_profile_utils.py` | `finbot/core/domain/services/_profile_utils.py` | Value area expansion algorithm | numpy | Shared utility for volume/market profile |
| `finbar/core/domain/services/content_hash.py` | `finbot/core/domain/services/content_hash.py` | Deterministic hash of strategy content | None | Needed for strategy_hash in signal keys |

---

## Tier 5 — Parser/resolver stack

Needed to load Finbar YAML/JSON strategies into domain entities. This is the
largest dependency chain.

| Finbar source | Finbot target | Needed for | Dependencies | Notes |
|---|---|---|---|---|
| `finbar/core/application/services/strategy_definition_parser.py` | `finbot/infrastructure/strategy/strategy_definition_parser.py` | Main YAML/JSON parser entry point | All resolvers, limit rules, warning rules | Core parser |
| `finbar/core/application/services/strategy_condition_parser.py` | `finbot/infrastructure/strategy/strategy_condition_parser.py` | Parse condition trees from YAML | `strategy_operand_parser.py`, `strategy_condition_group_parser.py` | |
| `finbar/core/application/services/strategy_condition_group_parser.py` | `finbot/infrastructure/strategy/strategy_condition_group_parser.py` | Parse nested condition groups | `strategy_condition_parser.py` | |
| `finbar/core/application/services/strategy_operand_parser.py` | `finbot/infrastructure/strategy/strategy_operand_parser.py` | Parse operands from YAML | `indicator_capability_provider` interface | |
| `finbar/core/application/services/strategy_definition_parse_helpers.py` | `finbot/infrastructure/strategy/strategy_definition_parse_helpers.py` | Shared parsing utilities | None | |
| `finbar/core/application/services/strategy_parameter_resolver.py` | `finbot/infrastructure/strategy/strategy_parameter_resolver.py` | Resolve parameter definitions and defaults | `strategy_parameter.py` | |
| `finbar/core/application/services/strategy_indicator_resolver.py` | `finbot/infrastructure/strategy/strategy_indicator_resolver.py` | Resolve indicator aliases to concrete types | `indicator_capability_provider` interface | |
| `finbar/core/application/services/strategy_risk_resolver.py` | `finbot/infrastructure/strategy/strategy_risk_resolver.py` | Parse risk section from YAML | `risk_spec.py`, `indicator_capability_provider` interface | |
| `finbar/core/application/services/strategy_timeframe_resolver.py` | `finbot/infrastructure/strategy/strategy_timeframe_resolver.py` | Parse timeframe declarations | `timeframe_declaration.py`, `informative_timeframe.py` | |
| `finbar/core/application/services/strategy_feature_resolver.py` | `finbot/infrastructure/strategy/strategy_feature_resolver.py` | Parse feature declarations | `feature_spec.py`, `formula_node.py`, `indicator_capability_provider` | |
| `finbar/core/application/services/strategy_indicator_catalog.py` | `finbot/infrastructure/strategy/strategy_indicator_catalog.py` | Built-in indicator capability registry | `indicator_capability_provider` interface | |
| `finbar/core/application/services/strategy_capability_service.py` | `finbot/infrastructure/strategy/strategy_capability_service.py` | Query indicator capabilities | `indicator_capability_provider` | |
| `finbar/core/application/services/strategy_definition_serializer.py` | `finbot/infrastructure/strategy/strategy_definition_serializer.py` | Serialize definition to canonical form | `condition_tree_visitor` | |
| `finbar/core/application/services/serialize_group_visitor.py` | `finbot/infrastructure/strategy/serialize_group_visitor.py` | Condition tree serialization visitor | `condition_tree_visitor` interface | |
| `finbar/core/application/services/strategy_limit_rule.py` | `finbot/infrastructure/strategy/strategy_limit_rule.py` | Limit rule interface | None | ABC for validation rules |
| `finbar/core/application/services/strategy_limit_rules.py` | `finbot/infrastructure/strategy/strategy_limit_rules.py` | Default limit rules (max indicators, max features, etc.) | `strategy_limit_rule.py` | |
| `finbar/core/application/services/strategy_warning_rule.py` | `finbot/infrastructure/strategy/strategy_warning_rule.py` | Warning rule interface | None | ABC for warning rules |
| `finbar/core/application/services/strategy_warning_rules.py` | `finbot/infrastructure/strategy/strategy_warning_rules.py` | Default warning rules (no exit, no stop) | `strategy_warning_rule.py` | |
| `finbar/core/application/services/max_indicators_limit_rule.py` | `finbot/infrastructure/strategy/max_indicators_limit_rule.py` | Enforce max indicator count | `strategy_limit_rule.py` | |
| `finbar/core/application/services/max_features_limit_rule.py` | `finbot/infrastructure/strategy/max_features_limit_rule.py` | Enforce max feature count | `strategy_limit_rule.py` | |
| `finbar/core/application/services/max_parameters_limit_rule.py` | `finbot/infrastructure/strategy/max_parameters_limit_rule.py` | Enforce max parameter count | `strategy_limit_rule.py` | |
| `finbar/core/application/services/max_condition_depth_limit_rule.py` | `finbot/infrastructure/strategy/max_condition_depth_limit_rule.py` | Enforce max condition nesting depth | `strategy_limit_rule.py` | |
| `finbar/core/application/services/no_exit_warning_rule.py` | `finbot/infrastructure/strategy/no_exit_warning_rule.py` | Warn on strategies without exit rules | `strategy_warning_rule.py` | |
| `finbar/core/application/services/no_stop_warning_rule.py` | `finbot/infrastructure/strategy/no_stop_warning_rule.py` | Warn on strategies without stop loss | `strategy_warning_rule.py` | |
| `finbar/core/application/services/required_column_collector.py` | `finbot/infrastructure/strategy/required_column_collector.py` | Collect required bar columns from definition | `condition_tree_visitor` | |
| `finbar/core/application/services/feature_input_column_collector.py` | `finbot/infrastructure/strategy/feature_input_column_collector.py` | Collect indicator columns needed by features | None | |
| `finbar/core/application/services/strategy_schema_provider.py` | `finbot/infrastructure/strategy/strategy_schema_provider.py` | JSON schema for strategy validation | None | |
| `finbar/core/application/services/description_visitor.py` | `finbot/infrastructure/strategy/description_visitor.py` | Human-readable condition description visitor | `condition_tree_visitor` | Nice-to-have for explainability |

---

## Tier 6 — Indicator calculation infrastructure

| Finbar source | Finbot target | Needed for | Dependencies | Notes |
|---|---|---|---|---|
| `finbar/infrastructure/services/pandas_ta_indicator_calculator.py` | `finbot/infrastructure/strategy/pandas_ta_indicator_calculator.py` | Compute indicators (ATR, VP, etc.) on bar DataFrames | `indicator_calculator` interface, `pandas-ta` | |
| `finbar/infrastructure/services/pandas_bar_frame_converter.py` | `finbot/infrastructure/strategy/pandas_bar_frame_converter.py` | Convert between bar dict/DataFrame formats | pandas | May simplify for Finbot |
| `finbar/infrastructure/services/pandas_signal_calculator.py` | `finbot/infrastructure/strategy/pandas_signal_calculator.py` | Compute AMT signals on DataFrames | `amt_signals.py`, `auction_state.py` | Thin wrapper around domain services |
| `finbar/infrastructure/services/pandas_strategy_feature_calculator.py` | `finbot/infrastructure/strategy/pandas_strategy_feature_calculator.py` | Feature computation on bars | pandas | Not needed by AMT strategies, only for formula features |
| `finbar/infrastructure/services/pandas_formula_feature_calculator.py` | `finbot/infrastructure/strategy/pandas_formula_feature_calculator.py` | Evaluate formula AST on bars | `formula_node.py`, pandas | Only if formula features are supported |

---

## NOT copied — Do not copy these

These should never appear in Finbot:

- `finbar/presentation/` — REST API, MCP tools, HTTP servers
- `finbar/startup/` — FastAPI/MCP composition roots
- `finbar/infrastructure/repositories/sql_*.py` — SQLAlchemy repositories
- `finbar/infrastructure/tables/` — ORM table definitions
- `finbar/infrastructure/services/backtest_*.py` — Backtesting engine
- `finbar/infrastructure/services/position_*.py` — Backtest position sizing/execution
- `finbar/infrastructure/services/grid_search_optimizer.py` — Optimization
- `finbar/infrastructure/services/walk_forward_optimizer.py` — Walk-forward
- `finbar/infrastructure/services/coinglass_*.py` — Coinglass data fetcher
- `finbar/infrastructure/services/hyperliquid_fetcher.py` — Hyperliquid historical data fetcher
- `finbar/infrastructure/services/yfinance_stock_fetcher.py` — Yahoo Finance fetcher
- `finbar/infrastructure/services/fetch_job*.py` — Async fetch job manager
- `finbar/infrastructure/services/in_memory_*_job_manager.py` — Job managers
- `finbar/infrastructure/services/indicator_job_runner.py` — Job runner
- `finbar/infrastructure/services/margin_account_manager.py` — Margin accounting
- `finbar/infrastructure/services/bar_merger.py` — Timeframe bar merging
- `finbar/infrastructure/services/bar_validator.py` — Bar validation
- `finbar/infrastructure/services/builtin_strategy_provider.py` — Built-in strategies
- `finbar/infrastructure/services/composite_strategy_provider.py` — Provider composition
- `finbar/infrastructure/services/database_strategy_provider.py` — DB-backed provider
- `finbar/infrastructure/services/strategy_definition_factory.py` — Factory for definitions
- `finbar/core/application/use_cases/` — All use cases (Finbot has its own)
- `finbar/core/application/dto/` — All DTOs (Finbot has its own)
- `finbar/core/domain/entities/` backtest/optimization entities:
  - `backtest_diagnostic.py`, `confidence_score.py`, `data_mode.py`, `data_source.py`
  - `derivatives_metrics.py`, `execution_config.py`, `indicator_job.py`
  - `interval.py`, `leverage_config.py`, `margin_account.py`
  - `optimization_*.py`, `param_range.py`, `pending_*.py`
  - `portfolio_*.py`, `price_bar.py`, `risk_factor.py`, `rsi_zone.py`
  - `strategy_document.py`, `symbol_info.py`, `trade_record.py`
  - `walk_forward_*.py`, `market_profile_result.py`
- `finbar/core/domain/services/` backtest services:
  - `backtest_metrics.py`, `coil_detector.py`, `composite_vp.py`
  - `confidence_scorer.py`, `correlation.py`, `indicator_value_mapper.py`
  - `market_profile.py`, `profile_shape.py`, `profile_shape_wrappers.py`
  - `proxy_indicator.py`, `rolling_metrics.py`, `vwap_bands.py`
  - `wyckoff_phase.py`, `wyckoff_wrappers.py`, `annualization.py`

---

## Copy phases

| Copy phase | What to copy | Implementation phase |
|---|---|---|
| Phase 2 | Domain entities (Tier 2) | Phase 2 — Strategy domain entities |
| Phase 3 | Parser stack (Tier 5) | Phase 3 — YAML/JSON loader |
| Phase 5 | Condition evaluator (Tier 1) + entities | Phase 5 — Condition evaluator |
| Phase 6 | Risk calculator (Tier 1) + entities | Phase 6 — Risk calculator |
| Phase 7 | Domain services (Tier 4) + indicator infra (Tier 6) | Phase 7 — Indicator engine |
| Phase 8 | Rule-based strategy (Tier 1) | Phase 8 — Strategy evaluator |

Total files to copy: ~53 (includes full parser stack for schema support).

---

## Review checklist

- [ ] Each copied file has a clear reason documented above.
- [ ] No presentation/startup/repository/backtest code is copied.
- [ ] All imports are rewritten from `finbar.*` to `finbot.*`.
- [ ] Architecture tests verify copied code does not import `finbar`.
- [ ] Optional parity tests exist for runtime components.
