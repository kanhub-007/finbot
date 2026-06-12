"""Risk event record — a risk gate decision captured for audit."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True)
class RiskEventRecord:
    """Record of a risk decision — accepted or rejected — for traceability."""

    bot_run_id: str
    event_type: str  # stale_data / max_position / daily_loss / duplicate / …
    signal_key: str
    decision: str  # accepted / rejected
    reason: str = ""
    event_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
