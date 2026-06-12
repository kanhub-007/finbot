"""Bot run — a single execution session of the trading bot."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True)
class BotRun:
    """Identifies one continuous bot session.

    Created at startup and referenced by all persisted records
    (signals, orders, fills, risk events, audit log) for that
    session.
    """

    strategy_name: str
    strategy_hash: str
    symbol: str
    interval: str
    mode: str
    run_id: str = field(default_factory=lambda: uuid4().hex)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
