"""Factory: package StrategyDefinition -> SharedRuntimeStrategyEvaluator.

Creates one package ``TradingStrategy`` per call (via the package
``StrategyDefinitionFactory``) and wraps it in a Finbot adapter. The
package strategy is stateful, so a fresh instance per session is
required.
"""

from finbar_strategy_runtime.domain.entities.strategy_definition import (
    StrategyDefinition,
)
from finbar_strategy_runtime.domain.interfaces.trading_strategy import TradingStrategy
from finbar_strategy_runtime.evaluation.strategy_definition_factory import (
    StrategyDefinitionFactory,
)

from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator
from finbot.core.domain.interfaces.strategy_evaluator_factory import (
    StrategyEvaluatorFactory,
)
from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator import (
    SharedRuntimeStrategyEvaluator,
)


class SharedRuntimeStrategyEvaluatorFactory(StrategyEvaluatorFactory):
    """Create SharedRuntimeStrategyEvaluator instances via the package factory."""

    def __init__(
        self, package_factory: StrategyDefinitionFactory | None = None
    ) -> None:
        self._package_factory = package_factory or StrategyDefinitionFactory()

    def create(
        self,
        definition: StrategyDefinition,
        symbol: str,
        interval: str,
        strategy_hash: str,
    ) -> StrategyEvaluator:
        """Compile the definition into a package strategy and wrap it."""
        strategy: TradingStrategy = self._package_factory.create(definition)
        return SharedRuntimeStrategyEvaluator(
            strategy,
            symbol=symbol,
            interval=interval,
            strategy_hash=strategy_hash,
        )
