"""Reconciliation record — result of a position/order reconciliation pass."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True)
class ReconciliationRecord:
    """Outcome of comparing local state against exchange state.

    Run at startup and periodically to detect drift between the bot's
    view and the exchange's actual position/open orders.
    """

    bot_run_id: str
    position_matches: bool
    open_orders_match: bool
    exchange_state_json: str = "{}"
    details: str = ""
    reconciliation_id: str = field(default_factory=lambda: uuid4().hex)
    reconciled_at: datetime = field(default_factory=lambda: datetime.now(UTC))
