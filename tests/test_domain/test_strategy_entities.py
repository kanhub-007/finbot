"""Tests for copied strategy domain entities."""

import pytest

from finbot.core.domain.entities.condition import Condition
from finbot.core.domain.entities.condition_group import ConditionGroup
from finbot.core.domain.entities.data_mode import DataMode
from finbot.core.domain.entities.feature_spec import FeatureSpec
from finbot.core.domain.entities.formula_node import FormulaNode
from finbot.core.domain.entities.indicator_spec import IndicatorSpec
from finbot.core.domain.entities.operand import Operand
from finbot.core.domain.entities.side_rules import SideRules
from finbot.core.domain.entities.signal_result import SignalResult
from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.entities.strategy_kind import StrategyKind
from finbot.core.domain.entities.strategy_meta import StrategyMeta
from finbot.core.domain.entities.strategy_parameter import StrategyParameter
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)
from finbot.core.domain.entities.strategy_validation_result import (
    StrategyValidationResult,
)
from finbot.core.domain.entities.timeframe_declaration import TimeframeDeclaration
from finbot.core.domain.entities.volume_profile_result import VolumeProfileResult


class TestStrategyDomainEntities:
    def test_condition_can_be_constructed(self) -> None:
        cond = Condition(left=Operand(kind="indicator", value="atr"), operator=">")
        assert cond.operator == ">"
        assert cond.left.kind == "indicator"
        assert cond.right is None

    def test_condition_group_supports_all_shape(self) -> None:
        group = ConditionGroup(
            kind="all",
            children=[
                ConditionGroup(
                    kind="condition",
                    condition=Condition(
                        left=Operand(kind="indicator", value="rsi"),
                        operator="<",
                        right=Operand(kind="literal", value=30),
                    ),
                )
            ],
        )
        assert group.kind == "all"
        assert len(group.children) == 1
        assert group.children[0].condition is not None

    def test_condition_group_supports_any_shape(self) -> None:
        group = ConditionGroup(kind="any", children=[])
        assert group.kind == "any"

    def test_condition_group_supports_not_shape(self) -> None:
        leaf = ConditionGroup(
            kind="condition",
            condition=Condition(
                left=Operand(kind="indicator", value="above_value"),
                operator="is_true",
            ),
        )
        group = ConditionGroup(kind="not", children=[leaf])
        assert group.kind == "not"
        assert len(group.children) == 1

    def test_strategy_definition_can_be_constructed(self) -> None:
        entry_cond = ConditionGroup(
            kind="condition",
            condition=Condition(
                left=Operand(kind="indicator", value="acceptance_into_value"),
                operator="is_true",
            ),
        )
        definition = StrategyDefinition(
            name="test_strategy",
            sides={
                "long": SideRules(side="long", entry=entry_cond),
            },
            schema_version="2.0",
            indicators=[
                IndicatorSpec(
                    name="atr",
                    type="atr",
                    concrete_name="atr",
                ),
            ],
        )
        assert definition.name == "test_strategy"
        assert definition.schema_version == "2.0"
        assert len(definition.indicators) == 1
        assert definition.indicators[0].type == "atr"

    def test_strategy_validation_result_reports_valid(self) -> None:
        result = StrategyValidationResult(valid=True)
        assert result.valid is True
        assert result.errors == []
        assert result.definition is None

    def test_strategy_validation_result_reports_invalid(self) -> None:
        error = StrategyValidationError(path="$.name", message="name is required")
        result = StrategyValidationResult(valid=False, errors=[error])
        assert result.valid is False
        assert len(result.errors) == 1
        assert result.errors[0].path == "$.name"

    def test_signal_result_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        signal = SignalResult(action="buy", direction="long")
        assert signal.action == "buy"
        with pytest.raises(FrozenInstanceError):
            signal.action = "sell"  # type: ignore[misc]

    def test_volume_profile_result_is_mutable(self) -> None:
        vp = VolumeProfileResult(
            poc=100.0,
            vah=102.0,
            val=98.0,
            total_volume=10000.0,
            value_area_volume=6800.0,
            bucket_size=0.5,
            num_buckets=50,
        )
        assert vp.poc == 100.0
        # Not frozen — should allow mutation.
        vp.poc = 101.0
        assert vp.poc == 101.0

    def test_strategy_meta_can_be_constructed(self) -> None:
        meta = StrategyMeta(
            name="test",
            variant=DataMode.REAL,
            description="A test strategy",
            required_indicators=["atr"],
            kind=StrategyKind.USER_DEFINED,
        )
        assert meta.name == "test"
        assert meta.variant == DataMode.REAL
        assert meta.kind == StrategyKind.USER_DEFINED

    def test_strategy_parameter_has_default(self) -> None:
        param = StrategyParameter(
            name="stop_mult",
            type="float",
            default=3.5,
            minimum=2.0,
            maximum=5.0,
        )
        assert param.default == 3.5
        assert param.minimum == 2.0

    def test_timeframe_declaration_supports_primary_only(self) -> None:
        decl = TimeframeDeclaration(primary="1h")
        assert decl.primary == "1h"
        assert decl.has_informative() is False
        assert decl.interval_for("primary") == "1h"
        assert decl.interval_for("nonexistent") is None

    def test_formula_node_can_be_constructed(self) -> None:
        leaf = FormulaNode(kind="literal", value=1.5, label="threshold")
        assert leaf.kind == "literal"
        assert leaf.value == 1.5
        assert leaf.left is None

        binary = FormulaNode(op=">", kind="operator", left=leaf, right=leaf)
        assert binary.op == ">"
        assert binary.left is leaf

    def test_feature_spec_can_be_constructed(self) -> None:
        spec = FeatureSpec(name="rolling_high", type="rolling_max", window=20)
        assert spec.name == "rolling_high"
        assert spec.window == 20
