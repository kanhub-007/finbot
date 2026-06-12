"""Domain entity representing current exchange position state."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PositionSnapshot:
    """Current position state for one symbol."""

    symbol: str
    direction: str
    size: Decimal
    entry_price: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")
