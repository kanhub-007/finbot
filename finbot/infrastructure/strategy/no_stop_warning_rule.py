"""NoStopWarningRule — warn when no stop-loss is configured."""

from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)
from finbot.infrastructure.strategy.strategy_warning_rule import StrategyWarningRule


class NoStopWarningRule(StrategyWarningRule):
    """Warn when no stop-loss is configured for a strategy."""

    def check(self, definition: StrategyDefinition) -> StrategyValidationError | None:
        if definition.risk is None or definition.risk.stop_loss_type == "none":
            return StrategyValidationError(
                path="$.risk",
                message="no stop-loss defined — strategy may hold losing positions",
                code="no_stop",
            )
        return None
