"""Adapter: package TradingStrategy -> Finbot StrategyEvaluator.

This is the single bridge between the shared runtime package's
``TradingStrategy.on_bar`` (which returns a package ``SignalResult``)
and Finbot's live-trading ``SignalDecision`` (typed enum with live
idempotency fields). It is the only place that knows about both types.

Package imports live here (infrastructure) so domain/application stay
clean; the public method signature is the Finbot interface only.
"""

from decimal import Decimal
from typing import Any

from finbar_strategy_runtime.domain.entities.signal_result import SignalResult
from finbar_strategy_runtime.domain.interfaces.trading_strategy import TradingStrategy

from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator


class SharedRuntimeStrategyEvaluator(StrategyEvaluator):
    """Wrap a package TradingStrategy and emit a Finbot SignalDecision.

    One evaluator owns one package ``TradingStrategy`` instance for the
    lifetime of a live session (the package strategy is stateful — it
    holds crossover tracking state). Never recreate mid-session.
    """

    def __init__(
        self,
        strategy: TradingStrategy,
        *,
        symbol: str,
        interval: str,
        strategy_hash: str,
    ) -> None:
        self._strategy = strategy
        self._symbol = symbol
        self._interval = interval
        self._strategy_hash = strategy_hash
        self._candle_timestamp: int = 0

    def evaluate(
        self,
        enriched_bar: dict[str, Any],
        position: PositionSnapshot,
    ) -> SignalDecision:
        """Evaluate one enriched closed bar and return a typed signal.

        Args:
            enriched_bar: OHLCV + indicator columns. ``candle_timestamp``
                drives the idempotency key; falls back to a monotonic
                counter when absent so signal_key stays session-stable.
            position: current Finbot position; its direction resolves the
                exit side which the package SignalResult omits.
        """
        self._candle_timestamp = int(
            enriched_bar.get("candle_timestamp", self._candle_timestamp + 1)
        )

        package_position = {
            "size": float(position.size),
            "direction": _direction_str(position.direction),
        }
        result = self._strategy.on_bar(enriched_bar, package_position)
        action = _map_signal(result, position.direction)

        return SignalDecision(
            action=action,
            symbol=self._symbol,
            interval=self._interval,
            candle_timestamp=self._candle_timestamp,
            strategy_hash=self._strategy_hash,
            confidence=result.confidence,
            stop_price=_to_decimal(result.stop_price),
            target_price=_to_decimal(result.target_price),
        )

    def reset(self) -> None:
        """Reset crossover state for a new session."""
        self._strategy.on_reset()
        self._candle_timestamp = 0


def _direction_str(direction: PositionDirection) -> str:
    """Map Finbot PositionDirection -> package position dict direction."""
    if direction == PositionDirection.LONG:
        return "long"
    if direction == PositionDirection.SHORT:
        return "short"
    return ""  # FLAT


def _to_decimal(value: float) -> Decimal | None:
    """Convert a package price float to a Decimal, treating 0 as absent."""
    if not value:
        return None
    return Decimal(str(value))


def _map_signal(
    result: SignalResult, position_direction: PositionDirection
) -> SignalAction:
    """Map package SignalResult (+ current side) -> Finbot SignalAction.

    Authoritative mapping (see 03-domain.md): on exit the package result
    does not carry the side, so it is resolved from the current position
    direction. Anything unmappable raises ValueError rather than silently
    degrading to HOLD.
    """
    action = result.action
    direction = result.direction

    if action == "hold":
        return SignalAction.HOLD
    if action == "buy" and direction == "long":
        return SignalAction.LONG_ENTRY
    if action == "sell" and direction == "short":
        return SignalAction.SHORT_ENTRY
    if direction == "exit":
        if position_direction == PositionDirection.LONG:
            return SignalAction.LONG_EXIT
        if position_direction == PositionDirection.SHORT:
            return SignalAction.SHORT_EXIT
    raise ValueError(
        f"Unmappable package signal: action={action!r} direction={direction!r}"
    )
