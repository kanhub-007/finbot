"""Architecture guardrail: copied Finbar strategy runtime is fully removed.

After adopting the ``finbar-strategy-runtime`` package, Finbot must not
contain its own copies of the parser/evaluator/indicator engine or the
copied strategy domain entities. This test locks that in (ADR-4: single
source of truth).
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Copied strategy runtime modules under infrastructure/strategy/ that must
# be gone (their package equivalents are used instead).
_DELETED_RUNTIME_MODULES = [
    "condition_evaluator",
    "description_visitor",
    "feature_input_column_collector",
    "indicator_registry",
    "json_risk_price_calculator",
    "json_rule_based_strategy",
    "max_condition_depth_limit_rule",
    "max_features_limit_rule",
    "max_indicators_limit_rule",
    "max_parameters_limit_rule",
    "no_exit_warning_rule",
    "no_stop_warning_rule",
    "pandas_signal_calculator",
    "pandas_strategy_feature_calculator",
    "pandas_formula_feature_calculator",
    "pandas_ta_indicator_calculator",
    "required_column_collector",
    "serialize_group_visitor",
    "strategy_capability_service",
    "strategy_condition_group_parser",
    "strategy_condition_parser",
    "strategy_definition_parse_helpers",
    "strategy_definition_parser",
    "strategy_definition_serializer",
    "strategy_feature_resolver",
    "strategy_indicator_catalog",
    "strategy_indicator_resolver",
    "strategy_limit_rule",
    "strategy_limit_rules",
    "strategy_operand_parser",
    "strategy_parameter_resolver",
    "strategy_risk_resolver",
    "strategy_schema_provider",
    "strategy_timeframe_resolver",
    "strategy_warning_rule",
    "strategy_warning_rules",
]

# Copied strategy domain entities that must be gone.
_DELETED_ENTITIES = [
    "condition",
    "condition_group",
    "data_mode",
    "feature_spec",
    "formula_node",
    "indicator_spec",
    "informative_timeframe",
    "interval",
    "operand",
    "risk_spec",
    "side_rules",
    "signal_result",
    "strategy_definition",
    "strategy_kind",
    "strategy_meta",
    "strategy_parameter",
    "strategy_validation_error",
    "strategy_validation_result",
    "timeframe_declaration",
    "volume_profile_result",
]

# Old evaluator adapters that must be gone (replaced by SharedRuntime*).
_DELETED_ADAPTERS = [
    "finbot/infrastructure/adapters/rule_based_strategy_evaluator.py",
    "finbot/infrastructure/adapters/rule_based_strategy_evaluator_factory.py",
    "finbot/infrastructure/adapters/finbar_strategy_evaluator.py",
]


@pytest.mark.parametrize("module", _DELETED_RUNTIME_MODULES)
def test_copied_runtime_module_removed(module: str) -> None:
    target = ROOT / "finbot" / "infrastructure" / "strategy" / f"{module}.py"
    assert not target.exists(), (
        f"Copied runtime module still present: {target}. "
        f"The package must be the single source of truth (ADR-4)."
    )


def test_copied_indicators_directory_removed() -> None:
    target = ROOT / "finbot" / "infrastructure" / "strategy" / "indicators"
    assert not target.exists(), f"Copied indicators directory still present: {target}."


@pytest.mark.parametrize("entity", _DELETED_ENTITIES)
def test_copied_strategy_entity_removed(entity: str) -> None:
    target = ROOT / "finbot" / "core" / "domain" / "entities" / f"{entity}.py"
    assert not target.exists(), (
        f"Copied strategy entity still present: {target}. "
        f"Use the package entity from finbar_strategy_runtime.domain.entities."
    )


@pytest.mark.parametrize("adapter", _DELETED_ADAPTERS)
def test_old_evaluator_adapter_removed(adapter: str) -> None:
    target = ROOT / adapter
    assert not target.exists(), (
        f"Old evaluator adapter still present: {target}. "
        f"Replaced by SharedRuntimeStrategyEvaluator(_Factory)."
    )


def test_no_finbar_strategy_evaluator_placeholder_remains() -> None:
    """The FinbarStrategyEvaluator placeholder must be deleted."""
    for base in (ROOT / "finbot").rglob("*.py"):
        text = base.read_text(encoding="utf-8")
        assert (
            "FinbarStrategyEvaluator" not in text
        ), f"{base} still references FinbarStrategyEvaluator."
