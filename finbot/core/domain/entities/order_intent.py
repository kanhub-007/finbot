"""Domain entity describing a desired exchange order."""

from dataclasses import dataclass, replace
from decimal import Decimal

from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType


@dataclass(frozen=True)
class OrderIntent:
    """A strategy-generated order request before exchange submission."""

    symbol: str
    side: OrderSide
    size: Decimal
    order_type: OrderType
    signal_key: str = ""
    reduce_only: bool = False
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
    cloid: str | None = None

    def with_cloid(self, cloid: str) -> "OrderIntent":
        """Return a copy of this intent with *cloid* set.

        Safe for frozen dataclasses — uses ``dataclasses.replace``.
        """
        return replace(self, cloid=cloid)
