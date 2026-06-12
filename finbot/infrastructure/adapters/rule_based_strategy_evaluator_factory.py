"""Rule-based strategy evaluator factory."""

from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator
from finbot.core.domain.interfaces.strategy_evaluator_factory import (
    StrategyEvaluatorFactory,
)
from finbot.infrastructure.adapters.rule_based_strategy_evaluator import (
    RuleBasedStrategyEvaluator,
)


class RuleBasedStrategyEvaluatorFactory(StrategyEvaluatorFactory):
    """Factory that creates RuleBasedStrategyEvaluator instances."""

    def create(
        self,
        definition: StrategyDefinition,
        symbol: str,
        interval: str,
        strategy_hash: str,
    ) -> StrategyEvaluator:
        return RuleBasedStrategyEvaluator(
            definition,
            symbol=symbol,
            interval=interval,
            strategy_hash=strategy_hash,
        )
