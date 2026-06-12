"""Warning rule defaults for strategy validation."""

from finbot.infrastructure.strategy.no_exit_warning_rule import NoExitWarningRule
from finbot.infrastructure.strategy.no_stop_warning_rule import NoStopWarningRule
from finbot.infrastructure.strategy.strategy_warning_rule import StrategyWarningRule

DEFAULT_WARNING_RULES: list[StrategyWarningRule] = [
    NoExitWarningRule(),
    NoStopWarningRule(),
]
