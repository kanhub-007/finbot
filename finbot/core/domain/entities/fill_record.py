"""Fill record — a single trade fill from the exchange."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4


@dataclass(frozen=True)
class FillRecord:
    """One trade fill event received from the exchange."""

    bot_run_id: str
    order_id: str
    symbol: str
    side: str  # buy / sell
    size: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    fill_id: str = field(default_factory=lambda: uuid4().hex)
    filled_at: datetime = field(default_factory=lambda: datetime.now(UTC))
