"""ManualOrderDraft — stashed manual-order params awaiting confirmation.

Replaces the prior ``session.interval = "long|0.1|sl|tp"`` serialised
stash (M9 / primitive obsession) with a typed value object. Read by
``_handle_confirm_callback`` on the Confirm callback.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from finbot.core.domain.entities.order_side import OrderSide


@dataclass(frozen=True)
class ManualOrderDraft:
    """Stashed parameters for a manual order awaiting confirmation.

    Attributes
    ----------
    side:
        Direction of the entry (BUY for long, SELL for short).
    size:
        Order size in base units.
    sl_price:
        Optional stop-loss price (absolute or ``"2%"``).
    tp_price:
        Optional take-profit price (absolute or ``"2%"``).
    """

    side: OrderSide
    size: Decimal
    sl_price: Decimal | str | None = None
    tp_price: Decimal | str | None = None
