"""ConditionGroup entity for nested strategy conditions."""

from dataclasses import dataclass, field

from finbot.core.domain.entities.condition import Condition


@dataclass(frozen=True)
class ConditionGroup:
    """A nested boolean condition tree.

    A group can be an ``all`` node, an ``any`` node, a ``not`` node, or a leaf
    wrapping one atomic condition.
    """

    kind: str
    """Group kind: all, any, not, or condition."""

    children: list["ConditionGroup"] = field(default_factory=list)
    """Child condition groups for boolean nodes."""

    condition: Condition | None = None
    """Atomic condition for leaf nodes."""
