"""TradeExecuted domain event — raised when a fill has been persisted."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TradeExecuted:
    """Domain event raised after a fill is persisted and applied to a trade.

    This is the event that triggers proactive Telegram notifications
    for trade fills.
    """

    run_id: str
    symbol: str
    side: str
    size: str
    price: str
    pnl: str | None
    order_id: str
    timestamp: datetime
