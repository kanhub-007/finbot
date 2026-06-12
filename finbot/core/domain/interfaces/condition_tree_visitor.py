"""ConditionTreeVisitor interface for traversing condition trees."""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.condition import Condition
from finbot.core.domain.entities.condition_group import ConditionGroup


class ConditionTreeVisitor(ABC):
    """Base visitor for strategy condition trees.

    Subclasses override visit_condition for atomic conditions and
    may override visit_group_enter / visit_group_leave for group
    boundaries (depth tracking, formatting delimiters, etc.).
    """

    def visit_group(self, group: ConditionGroup | None) -> None:
        """Visit a group and recursively traverse its children."""
        if group is None:
            return
        self.visit_group_enter(group)
        if group.condition is not None:
            self.visit_condition(group.condition)
        for child in group.children:
            self.visit_group(child)
        self.visit_group_leave(group)

    @abstractmethod
    def visit_condition(self, condition: Condition) -> None:
        """Visit an atomic condition."""

    def visit_group_enter(self, group: ConditionGroup) -> None:
        """Called before visiting a group's children."""

    def visit_group_leave(self, group: ConditionGroup) -> None:
        """Called after visiting a group's children."""
