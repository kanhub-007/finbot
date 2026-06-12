"""Rule-based strategy evaluator — adapter from Finbar to Finbot."""

from typing import Any

from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator
from finbot.infrastructure.strategy.json_rule_based_strategy import (
    JsonRuleBasedStrategy,
)


class RuleBasedStrategyEvaluator(StrategyEvaluator):
    """Wraps Finbar's JsonRuleBasedStrategy as a Finbot StrategyEvaluator.

    Translates between Finbar's SignalResult (raw strings) and Finbot's
    SignalDecision (typed enums with signal keys).
    """

    def __init__(
        self,
        definition: StrategyDefinition,
        symbol: str = "",
        interval: str = "",
        strategy_hash: str = "",
    ):
        self._strategy = JsonRuleBasedStrategy(definition)
        self._symbol = symbol
        self._interval = interval
        self._strategy_hash = strategy_hash
        self._candle_timestamp: int = 0

    def evaluate(
        self,
        enriched_bar: dict[str, Any],
        position: PositionSnapshot,
    ) -> SignalDecision:
        """Evaluate one enriched closed bar and return a typed signal."""
        self._candle_timestamp = int(
            enriched_bar.get("candle_timestamp", self._candle_timestamp + 1)
        )

        finbar_position = {
            "direction": str(position.direction),
            "size": float(position.size),
        }
        result = self._strategy.on_bar(enriched_bar, finbar_position)
        action = _map_action(result.action, result.direction)

        return SignalDecision(
            action=action,
            symbol=self._symbol,
            interval=self._interval,
            candle_timestamp=self._candle_timestamp,
            strategy_hash=self._strategy_hash,
            confidence=result.confidence,
            stop_price=(result.stop_price if result.stop_price else None),
            target_price=(result.target_price if result.target_price else None),
        )

    def reset(self) -> None:
        """Reset internal crossover state for a new run."""
        self._strategy.on_reset()
        self._candle_timestamp = 0


def _map_action(finbar_action: str, finbar_direction: str) -> SignalAction:
    """Convert Finbar's raw string action/direction to SignalAction enum.

    Finbar conventions:
      Entry: action="buy"/"sell", direction="long"/"short"
      Exit:  action="sell"/"buy", direction="exit"
    """
    if finbar_action == "hold":
        return SignalAction.HOLD
    if finbar_action == "buy":
        if finbar_direction == "exit":
            return SignalAction.SHORT_EXIT
        return SignalAction.LONG_ENTRY
    if finbar_action == "sell":
        if finbar_direction == "short":
            return SignalAction.SHORT_ENTRY
        if finbar_direction == "exit":
            return SignalAction.LONG_EXIT
        return SignalAction.LONG_EXIT
    return SignalAction.HOLD
