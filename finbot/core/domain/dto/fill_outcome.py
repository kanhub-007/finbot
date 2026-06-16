"""Fill outcome DTO — result of applying a fill to the Trade ledger."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FillOutcome:
    """Outcome of :meth:`TradeLedger.apply_fill` for one fill."""

    status: str  # "opened" | "accumulated" | "closed" | "partial" | "duplicate"
    position_id: str = ""
    realized_pnl: Decimal | None = None
