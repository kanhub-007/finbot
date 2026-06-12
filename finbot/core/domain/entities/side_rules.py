"""SideRules entity for JSON strategies."""

from dataclasses import dataclass

from finbot.core.domain.entities.condition_group import ConditionGroup


@dataclass(frozen=True)
class SideRules:
    """Entry and exit conditions for one trading side."""

    side: str
    """Trading side: long or short."""

    entry: ConditionGroup
    """Condition tree that opens this side when flat."""

    exit: ConditionGroup | None = None
    """Optional condition tree that closes this side when in a position."""

    entry_confidence: float = 0.7
    """Confidence to attach to entry signals."""

    exit_confidence: float = 0.7
    """Confidence to attach to exit signals."""
