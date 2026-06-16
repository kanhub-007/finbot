"""Trade — durable record of one position's lifecycle."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from finbot.core.domain.entities.position_direction import PositionDirection


@dataclass(frozen=True)
class Trade:
    """Durable record of one position's lifecycle (open → close).

    Distinct from the transient :class:`PositionSnapshot` (exchange read).
    Tracks entry, exit, fees, and realized profit/loss for a single
    position.
    """

    position_id: str
    bot_run_id: str
    symbol: str
    side: PositionDirection  # LONG or SHORT (never FLAT)
    size: Decimal  # current open size (base units)
    entry_price: Decimal | None  # volume-weighted avg; None when reconstructed
    opened_at: datetime  # first entry fill time (UTC)
    status: str = "open"  # "open" | "closed"
    realized_pnl: Decimal = Decimal("0")
    total_fee: Decimal = Decimal("0")
    closed_at: datetime | None = None
    close_price: Decimal | None = None
    strategy_hash: str = ""
    entry_signal_key: str = ""
