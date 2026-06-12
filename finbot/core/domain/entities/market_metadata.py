"""Market metadata — per-symbol order constraints from the exchange."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class MarketMetadata:
    """Exchange-defined constraints for a single trading symbol.

    Used by the :class:`OrderNormalizer` to round sizes and prices
    to exchange-accepted precision and reject invalid orders.
    """

    symbol: str
    sz_decimals: int = 0
    """Number of decimal places for order size (e.g. 5 for BTC)."""
    price_tick: Decimal = Decimal("0")
    """Minimum price increment (tick size).  0 = unknown."""
    min_size: Decimal = Decimal("0")
    """Minimum order size in base units."""
    max_leverage: int = 0
    """Maximum allowed leverage.  0 = unknown."""
