"""Order type value object."""

from enum import StrEnum


class OrderType(StrEnum):
    """Kind of exchange order to submit."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    """Stop-loss trigger order (reduce-only)."""
    TAKE_PROFIT = "take_profit"
    """Take-profit trigger order (reduce-only)."""
