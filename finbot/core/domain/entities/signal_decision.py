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
        """Unique signal key for idempotent processing.

        Raises ValueError when any required key field is empty — this
        prevents accidental key collisions where every signal maps to
        the same default key ``::0:``.
        """
        if not self.symbol:
            raise ValueError("signal_key requires a non-empty symbol")
        if not self.interval:
            raise ValueError("signal_key requires a non-empty interval")
        if not self.candle_timestamp:
            raise ValueError("signal_key requires a positive candle_timestamp")
        if not self.strategy_hash:
            raise ValueError("signal_key requires a non-empty strategy_hash")
        return (
            f"{self.symbol}:{self.interval}:"
            f"{self.candle_timestamp}:{self.strategy_hash}"
        )
