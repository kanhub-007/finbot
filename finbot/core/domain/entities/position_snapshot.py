"""Domain entity representing current exchange position state."""

from dataclasses import dataclass
from decimal import Decimal

from finbot.core.domain.entities.position_direction import PositionDirection


@dataclass(frozen=True)
class PositionSnapshot:
    """Current position state for one symbol."""

    symbol: str
    direction: PositionDirection
    size: Decimal
    entry_price: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")
