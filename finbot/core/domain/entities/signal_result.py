"""Signal output from a trading strategy's on_bar() call.

Pure dataclass — no behavior, no ORM, no framework dependencies.

This entity intentionally uses raw ``str`` for ``action`` and ``direction``
instead of the Finbot-native ``SignalAction`` / ``PositionDirection`` enums.
It matches Finbar's wire format for runtime compatibility. The adapter layer
in ``infrastructure/strategy/`` converts to ``SignalDecision`` which uses enums.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SignalResult:
    """Unified signal output from a strategy evaluated on a single bar.

    The strategy evaluator calls strategy.on_bar(bar, position) for each
    bar and receives a SignalResult indicating buy/sell/hold with optional
    stop-loss and take-profit levels.
    """

    action: str = "hold"
    """Trade action: "buy", "sell", or "hold"."""

    direction: str = ""
    """Trade direction: "long", "short", or "exit"."""

    stop_price: float = 0.0
    """Optional stop-loss price level."""

    target_price: float = 0.0
    """Optional take-profit price level."""

    confidence: float = 0.0
    """Signal confidence 0-1, for signal ranking / position sizing."""

    position_size: int = 0
    """Suggested position size. 0 means engine computes default."""

    metadata: dict = field(default_factory=dict)
    """Strategy-specific metadata (e.g. indicator values at signal time)."""
