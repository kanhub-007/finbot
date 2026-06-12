"""DescriptionVisitor — build human-readable text from condition groups.

Internal visitor used by ExplainStrategyDefinitionUseCase.
"""

from finbot.core.domain.entities.condition import Condition
from finbot.core.domain.entities.condition_group import ConditionGroup
from finbot.core.domain.interfaces.condition_tree_visitor import ConditionTreeVisitor

_GROUP_FORMAT: dict[str, tuple[str, str]] = {
    "all": ("(", " AND "),
    "any": ("(", " OR "),
    "not": ("NOT (", " "),
}


class DescriptionVisitor(ConditionTreeVisitor):
    """Build a human-readable string from a condition group tree."""

    def __init__(self):
        self.result = ""
        self._stack: list[tuple[list[str], str, str]] = []

    def visit_group_enter(self, group: ConditionGroup) -> None:
        if group.kind == "condition":
            return
        opener, joiner = _GROUP_FORMAT[group.kind]
        self._stack.append(([], joiner, opener))

    def visit_group_leave(self, group: ConditionGroup) -> None:
        if group.kind == "condition":
            return
        parts, joiner, opener = self._stack.pop()
        rendered = opener + joiner.join(parts) + ")"
        if self._stack:
            self._stack[-1][0].append(rendered)
        else:
            self.result = rendered

    def visit_condition(self, condition: Condition) -> None:
        left = condition.left.label or str(condition.left.value)
        if condition.right is None:
            text = f"{left} {condition.operator}"
        else:
            right = condition.right.label or str(condition.right.value)
            text = f"{left} {condition.operator} {right}"
        if self._stack:
            self._stack[-1][0].append(text)
        else:
            self.result = text
