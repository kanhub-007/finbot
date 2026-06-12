"""Domain entity for a strategy evaluation result."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SignalDecision:
    """Normalized signal produced by a strategy adapter."""

    action: str
    direction: str = ""
    confidence: float = 0.0
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
