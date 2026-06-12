"""JsonRuleBasedStrategy — execute validated JSON strategies."""

from finbot.core.domain.entities.signal_result import SignalResult
from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.entities.strategy_meta import DataMode, StrategyMeta
from finbot.core.domain.interfaces.risk_price_calculator import RiskPriceCalculator
from finbot.core.domain.interfaces.trading_strategy import TradingStrategy
from finbot.infrastructure.strategy.condition_evaluator import (
    ConditionEvaluator,
    PrevValues,
)
from finbot.infrastructure.strategy.json_risk_price_calculator import (
    JsonRiskPriceCalculator,
)


class JsonRuleBasedStrategy(TradingStrategy):
    """TradingStrategy implementation for canonical JSON definitions."""

    def __init__(
        self,
        definition: StrategyDefinition,
        risk_calculator: RiskPriceCalculator | None = None,
    ):
        """Create a fresh executable strategy from a validated definition."""
        self._definition = definition
        self._risk_calculator = risk_calculator or JsonRiskPriceCalculator()
        self._evaluator = ConditionEvaluator()
        self._previous_values: PrevValues = {}

    def meta(self) -> StrategyMeta:
        """Return metadata for the JSON strategy."""
        return StrategyMeta(
            name=self._definition.name,
            variant=DataMode.REAL,
            description=self._definition.description,
            required_indicators=[
                item.concrete_name for item in self._definition.indicators
            ],
            params=self._definition.resolved_params,
        )

    def on_bar(self, bar: dict, position: dict) -> SignalResult:
        """Evaluate the strategy rules for one enriched OHLCV bar."""
        direction = str(position.get("direction", ""))
        size = float(position.get("size", 0) or 0)
        pending_values: PrevValues = {}

        if size != 0:
            signal = self._exit_signal(bar, direction, pending_values)
        else:
            signal = self._entry_signal(bar, pending_values)
        self._evaluator.commit(self._previous_values, pending_values)
        return signal

    def on_reset(self) -> None:
        """Reset crossover state before a backtest run."""
        self._previous_values.clear()

    def _entry_signal(self, bar: dict, pending_values: PrevValues) -> SignalResult:
        for side in ("long", "short"):
            rules = self._definition.sides.get(side)
            if rules is None:
                continue
            if self._evaluator.evaluate(
                rules.entry, bar, self._previous_values, pending_values
            ):
                stop, target = self._risk_calculator.calculate(
                    self._definition.risk,
                    bar,
                    side,
                )
                return SignalResult(
                    action="buy" if side == "long" else "sell",
                    direction=side,
                    confidence=rules.entry_confidence,
                    stop_price=stop,
                    target_price=target,
                )
        return SignalResult(action="hold")

    def _exit_signal(
        self, bar: dict, direction: str, pending_values: PrevValues
    ) -> SignalResult:
        rules = self._definition.sides.get(direction)
        if rules is None or rules.exit is None:
            return SignalResult(action="hold")
        if not self._evaluator.evaluate(
            rules.exit, bar, self._previous_values, pending_values
        ):
            return SignalResult(action="hold")
        return SignalResult(
            action="sell" if direction == "long" else "buy",
            direction="exit",
            confidence=rules.exit_confidence,
        )
