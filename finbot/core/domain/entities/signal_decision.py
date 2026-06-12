"""Domain entity for a strategy evaluation result."""

from dataclasses import dataclass
from decimal import Decimal

from finbot.core.domain.entities.signal_action import SignalAction


@dataclass(frozen=True)
class SignalDecision:
    """Normalized signal produced by a strategy adapter.

    The combination of symbol, interval, candle_timestamp, and strategy_hash
    forms the unique signal key used for idempotency.
    """

    action: SignalAction
    symbol: str = ""
    interval: str = ""
    candle_timestamp: int = 0
    strategy_hash: str = ""
    confidence: float = 0.0
    stop_price: Decimal | None = None
    target_price: Decimal | None = None

    @property
    def signal_key(self) -> str:
        """Unique signal key for idempotent processing."""
        return (
            f"{self.symbol}:{self.interval}:"
            f"{self.candle_timestamp}:{self.strategy_hash}"
        )
