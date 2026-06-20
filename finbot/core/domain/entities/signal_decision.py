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

    def __post_init__(self) -> None:
        """Warn on key fields that would produce an invalid signal key.

        Validation is deferred to :attr:`signal_key` (which raises) so
        tests that construct partial signals without accessing the key
        continue to work.  Non-HOLD signals with empty key fields get a
        runtime warning at construction time to catch misconfiguration
        early in production.
        """
        if self.action == SignalAction.HOLD:
            return
        missing: list[str] = []
        if not self.symbol:
            missing.append("symbol")
        if not self.interval:
            missing.append("interval")
        if not self.candle_timestamp:
            missing.append("candle_timestamp")
        if not self.strategy_hash:
            missing.append("strategy_hash")
        if missing:
            import warnings

            warnings.warn(
                f"SignalDecision({self.action.value}) has empty key fields "
                f"({', '.join(missing)}); signal_key will raise at access.",
                UserWarning,
                stacklevel=2,
            )

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
