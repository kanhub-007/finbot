"""SerializeGroupVisitor — build JSON dict tree from condition groups.

Internal visitor used by StrategyDefinitionSerializer.
"""

from finbot.core.domain.entities.condition import Condition
from finbot.core.domain.entities.condition_group import ConditionGroup
from finbot.core.domain.interfaces.condition_tree_visitor import ConditionTreeVisitor


class SerializeGroupVisitor(ConditionTreeVisitor):
    """Visitor that builds a JSON-serializable dict from condition groups."""

    def __init__(self):
        self.result: dict = {}
        self._stack: list[dict] = []

    def reset(self) -> None:
        self.result = {}
        self._stack = []

    def visit_group_enter(self, group: ConditionGroup) -> None:
        if group.kind == "condition":
            return
        node: dict = {group.kind: [] if group.kind != "not" else {}}
        if self._stack:
            current = self._stack[-1]
            kind_key = list(current.keys())[0]
            current[kind_key].append(node)
        else:
            self.result = node
        self._stack.append(node)

    def visit_group_leave(self, group: ConditionGroup) -> None:
        if group.kind != "condition" and self._stack:
            self._stack.pop()

    def visit_condition(self, condition: Condition) -> None:
        entry: dict = {"left": condition.left.value, "operator": condition.operator}
        if condition.right is not None:
            entry["right"] = condition.right.value
        if self._stack:
            current = self._stack[-1]
            kind_key = list(current.keys())[0]
            current[kind_key].append(entry)
        else:
            self.result = entry
