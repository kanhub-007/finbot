"""Order side value object."""

from enum import StrEnum


class OrderSide(StrEnum):
    """Buy or sell side of an order."""

    BUY = "buy"
    SELL = "sell"
