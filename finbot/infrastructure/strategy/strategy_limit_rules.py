"""Limit rule defaults for strategy validation."""

from finbot.infrastructure.strategy.max_condition_depth_limit_rule import (
    MaxConditionDepthLimitRule,
)
from finbot.infrastructure.strategy.max_features_limit_rule import (
    MaxFeaturesLimitRule,
)
from finbot.infrastructure.strategy.max_indicators_limit_rule import (
    MaxIndicatorsLimitRule,
)
from finbot.infrastructure.strategy.max_parameters_limit_rule import (
    MaxParametersLimitRule,
)
from finbot.infrastructure.strategy.strategy_limit_rule import StrategyLimitRule

DEFAULT_LIMIT_RULES: list[StrategyLimitRule] = [
    MaxParametersLimitRule(),
    MaxIndicatorsLimitRule(),
    MaxFeaturesLimitRule(),
    MaxConditionDepthLimitRule(),
]
