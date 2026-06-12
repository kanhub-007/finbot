"""Order type value object."""

from enum import StrEnum


class OrderType(StrEnum):
    """Kind of exchange order to submit."""

    MARKET = "market"
    LIMIT = "limit"
