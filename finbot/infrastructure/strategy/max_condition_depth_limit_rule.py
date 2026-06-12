"""MaxConditionDepthLimitRule — limit condition tree nesting depth."""

from finbot.core.domain.entities.condition_group import ConditionGroup
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)
from finbot.infrastructure.strategy.strategy_limit_rule import StrategyLimitRule


class MaxConditionDepthLimitRule(StrategyLimitRule):
    """Reject strategies with condition trees deeper than the allowed maximum."""

    def __init__(self, maximum: int = 5):
        self._maximum = maximum

    def check(
        self, definition, params, indicators, features
    ) -> StrategyValidationError | None:
        for side, rules in definition.sides.items():
            err = self._check_side(side, rules.entry, rules.exit)
            if err:
                return err
        return None

    def _check_side(
        self,
        side: str,
        entry: ConditionGroup,
        exit_group: ConditionGroup | None,
    ) -> StrategyValidationError | None:
        depth = _condition_depth(entry)
        if depth > self._maximum:
            return StrategyValidationError(
                path=f"$.sides.{side}.entry.condition",
                message=f"max depth {self._maximum} (got {depth})",
            )
        if exit_group is not None:
            depth = _condition_depth(exit_group)
            if depth > self._maximum:
                return StrategyValidationError(
                    path=f"$.sides.{side}.exit.condition",
                    message=f"max depth {self._maximum} (got {depth})",
                )
        return None


def _condition_depth(group: ConditionGroup) -> int:
    if group.kind == "condition":
        return 0
    return 1 + max((_condition_depth(child) for child in group.children), default=0)
