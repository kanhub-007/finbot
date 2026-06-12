"""ConditionEvaluator — evaluate strategy condition trees against bar data."""

from __future__ import annotations

import math
from typing import Any

from finbot.core.domain.entities.condition import Condition
from finbot.core.domain.entities.condition_group import ConditionGroup
from finbot.core.domain.entities.operand import Operand

PrevValues = dict[str, tuple[float, float]]
PendingValues = dict[str, tuple[float, float]]


class ConditionEvaluator:
    """Evaluate nested JSON strategy condition groups against enriched bars."""

    def evaluate(
        self,
        group: ConditionGroup | None,
        bar: dict,
        previous_values: PrevValues,
        pending_values: PendingValues | None = None,
    ) -> bool:
        """Evaluate a nested condition group against one enriched bar."""
        own_pending = pending_values is None
        current_values = pending_values if pending_values is not None else {}
        result = self._evaluate_group(group, bar, previous_values, current_values)
        if own_pending:
            self.commit(previous_values, current_values)
        return result

    def commit(
        self,
        previous_values: PrevValues,
        pending_values: PendingValues,
    ) -> None:
        """Commit crossover values collected during one bar evaluation."""
        previous_values.update(pending_values)

    def _evaluate_group(
        self,
        group: ConditionGroup | None,
        bar: dict,
        previous_values: PrevValues,
        pending_values: PendingValues,
    ) -> bool:
        """Evaluate a condition group using a per-bar crossover snapshot."""
        if group is None:
            return False
        if group.kind in ("all", "any"):
            results = [
                self._evaluate_group(child, bar, previous_values, pending_values)
                for child in group.children
            ]
            return all(results) if group.kind == "all" else any(results)
        if group.kind == "not":
            if not group.children:
                return False
            return not self._evaluate_group(
                group.children[0], bar, previous_values, pending_values
            )
        if group.kind == "condition" and group.condition is not None:
            return self._evaluate_condition(
                group.condition, bar, previous_values, pending_values
            )
        return False

    def _evaluate_condition(
        self,
        condition: Condition,
        bar: dict,
        previous_values: PrevValues,
        pending_values: PendingValues,
    ) -> bool:
        left = self._resolve_operand(condition.left, bar)
        operator = condition.operator

        if operator == "exists":
            return left is not None
        if operator == "missing":
            return left is None
        if operator == "is_true":
            return bool(left) is True
        if operator == "is_false":
            return bool(left) is False

        if condition.right is None:
            return False
        right = self._resolve_operand(condition.right, bar)

        if operator in ("between", "not_between"):
            result = self._between(left, right)
            return not result if operator == "not_between" else result

        left_number = self._to_float(left)
        right_number = self._to_float(right)
        if left_number is None or right_number is None:
            return False

        if operator in ("<", ">", "<=", ">=", "==", "!="):
            return self._compare(left_number, operator, right_number)
        if operator in ("crosses_above", "crosses_below"):
            return self._crossed(
                condition, left_number, right_number, previous_values, pending_values
            )
        return False

    @staticmethod
    def _resolve_operand(operand: Operand, bar: dict) -> Any:
        if operand.kind in ("field", "indicator", "feature", "column"):
            value = bar.get(str(operand.value))
            if value is not None:
                if not _is_nan(value):
                    return value
            for source in operand.sources:
                value = bar.get(source)
                if value is not None and not _is_nan(value):
                    return value
            return None
        return operand.value

    @staticmethod
    def _to_float(value: Any) -> float | None:
        # Booleans are ints in Python (True==1, False==0), so reject
        # them explicitly — we don't want True > 0.5 to succeed.
        if value is None or isinstance(value, bool):
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(result):
            return None
        return result

    @staticmethod
    def _between(left: Any, right: Any) -> bool:
        left_number = ConditionEvaluator._to_float(left)
        if left_number is None or not isinstance(right, list) or len(right) != 2:
            return False
        low = ConditionEvaluator._to_float(right[0])
        high = ConditionEvaluator._to_float(right[1])
        if low is None or high is None:
            return False
        return low <= left_number <= high

    @staticmethod
    def _compare(left: float, operator: str, right: float) -> bool:
        if operator == "<":
            return left < right
        if operator == ">":
            return left > right
        if operator == "<=":
            return left <= right
        if operator == ">=":
            return left >= right
        if operator == "==":
            return abs(left - right) < 1e-9
        if operator == "!=":
            return abs(left - right) >= 1e-9
        return False

    @staticmethod
    def _crossed(
        condition: Condition,
        left: float,
        right: float,
        previous_values: PrevValues,
        pending_values: PendingValues,
    ) -> bool:
        right_label = condition.right.label if condition.right is not None else ""
        key = f"{condition.left.label}:{right_label}:{condition.operator}"
        previous = previous_values.get(key)
        pending_values[key] = (left, right)
        if previous is None:
            return False
        previous_left, previous_right = previous
        if condition.operator == "crosses_above":
            return previous_left <= previous_right and left > right
        if condition.operator == "crosses_below":
            return previous_left >= previous_right and left < right
        return False


def _is_nan(value) -> bool:
    """Return True when value is a float NaN."""
    return isinstance(value, float) and value != value
