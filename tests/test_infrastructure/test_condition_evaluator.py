"""Tests for the condition evaluator."""

from finbot.core.domain.entities.condition import Condition
from finbot.core.domain.entities.condition_group import ConditionGroup
from finbot.core.domain.entities.operand import Operand
from finbot.infrastructure.strategy.condition_evaluator import ConditionEvaluator


def _evaluator() -> ConditionEvaluator:
    return ConditionEvaluator()


def _bar(**fields: object) -> dict:
    return dict(fields)


class TestConditionEvaluator:
    def test_is_true_operator(self) -> None:
        ev = _evaluator()
        group = ConditionGroup(
            kind="condition",
            condition=Condition(
                left=Operand(kind="indicator", value="acceptance_into_value"),
                operator="is_true",
            ),
        )
        assert ev.evaluate(group, _bar(acceptance_into_value=True), {}) is True
        assert ev.evaluate(group, _bar(acceptance_into_value=False), {}) is False

    def test_is_false_operator(self) -> None:
        ev = _evaluator()
        group = ConditionGroup(
            kind="condition",
            condition=Condition(
                left=Operand(kind="indicator", value="above_value"),
                operator="is_false",
            ),
        )
        assert ev.evaluate(group, _bar(above_value=False), {}) is True
        assert ev.evaluate(group, _bar(above_value=True), {}) is False

    def test_less_than_operator(self) -> None:
        ev = _evaluator()
        group = ConditionGroup(
            kind="condition",
            condition=Condition(
                left=Operand(kind="indicator", value="value_area_width_pct"),
                operator="<",
                right=Operand(kind="literal", value=1.5),
            ),
        )
        assert ev.evaluate(group, _bar(value_area_width_pct=1.2), {}) is True
        assert ev.evaluate(group, _bar(value_area_width_pct=2.0), {}) is False

    def test_greater_than_operator(self) -> None:
        ev = _evaluator()
        group = ConditionGroup(
            kind="condition",
            condition=Condition(
                left=Operand(kind="indicator", value="rsi"),
                operator=">",
                right=Operand(kind="literal", value=70),
            ),
        )
        assert ev.evaluate(group, _bar(rsi=75), {}) is True
        assert ev.evaluate(group, _bar(rsi=65), {}) is False

    def test_all_group_requires_all_true(self) -> None:
        ev = _evaluator()
        group = ConditionGroup(
            kind="all",
            children=[
                ConditionGroup(
                    kind="condition",
                    condition=Condition(
                        left=Operand(kind="indicator", value="acceptance_into_value"),
                        operator="is_true",
                    ),
                ),
                ConditionGroup(
                    kind="condition",
                    condition=Condition(
                        left=Operand(kind="indicator", value="value_area_width_pct"),
                        operator="<",
                        right=Operand(kind="literal", value=1.5),
                    ),
                ),
            ],
        )
        bar_all_true = _bar(acceptance_into_value=True, value_area_width_pct=1.0)
        bar_one_false = _bar(acceptance_into_value=False, value_area_width_pct=1.0)
        assert ev.evaluate(group, bar_all_true, {}) is True
        assert ev.evaluate(group, bar_one_false, {}) is False

    def test_any_group_requires_one_true(self) -> None:
        ev = _evaluator()
        group = ConditionGroup(
            kind="any",
            children=[
                ConditionGroup(
                    kind="condition",
                    condition=Condition(
                        left=Operand(kind="indicator", value="above_value"),
                        operator="is_true",
                    ),
                ),
                ConditionGroup(
                    kind="condition",
                    condition=Condition(
                        left=Operand(kind="indicator", value="rsi"),
                        operator=">",
                        right=Operand(kind="literal", value=80),
                    ),
                ),
            ],
        )
        assert ev.evaluate(group, _bar(above_value=True, rsi=50), {}) is True
        assert ev.evaluate(group, _bar(above_value=False, rsi=85), {}) is True
        assert ev.evaluate(group, _bar(above_value=False, rsi=50), {}) is False

    def test_not_group_inverts_result(self) -> None:
        ev = _evaluator()
        group = ConditionGroup(
            kind="not",
            children=[
                ConditionGroup(
                    kind="condition",
                    condition=Condition(
                        left=Operand(kind="indicator", value="above_value"),
                        operator="is_true",
                    ),
                ),
            ],
        )
        assert ev.evaluate(group, _bar(above_value=False), {}) is True
        assert ev.evaluate(group, _bar(above_value=True), {}) is False

    def test_missing_bar_field_returns_false(self) -> None:
        ev = _evaluator()
        group = ConditionGroup(
            kind="condition",
            condition=Condition(
                left=Operand(kind="indicator", value="nonexistent"),
                operator="is_true",
            ),
        )
        assert ev.evaluate(group, _bar(), {}) is False

    def test_crosses_above_requires_previous_value(self) -> None:
        ev = _evaluator()
        condition = Condition(
            left=Operand(kind="indicator", value="sma_fast", label="sma_fast"),
            operator="crosses_above",
            right=Operand(kind="indicator", value="sma_slow", label="sma_slow"),
        )
        group = ConditionGroup(kind="condition", condition=condition)

        prev: dict = {}
        # First bar: no previous value → no crossover.
        assert ev.evaluate(group, _bar(sma_fast=105, sma_slow=100), prev) is False
        # Now prev has sma_fast=105, sma_slow=100
        # Second bar: fast was below/equal, now above → cross above.
        prev.clear()
        prev["sma_fast:sma_slow:crosses_above"] = (100.0, 100.0)
        assert ev.evaluate(group, _bar(sma_fast=105, sma_slow=100), prev) is True

    def test_previous_values_committed_after_evaluation(self) -> None:
        ev = _evaluator()
        condition = Condition(
            left=Operand(kind="indicator", value="fast", label="fast"),
            operator="crosses_above",
            right=Operand(kind="indicator", value="slow", label="slow"),
        )
        group = ConditionGroup(kind="condition", condition=condition)
        prev: dict = {}

        ev.evaluate(group, _bar(fast=10, slow=8), prev)
        assert "fast:slow:crosses_above" in prev
        assert prev["fast:slow:crosses_above"] == (10.0, 8.0)

    def test_none_group_returns_false(self) -> None:
        ev = _evaluator()
        assert ev.evaluate(None, _bar(), {}) is False
