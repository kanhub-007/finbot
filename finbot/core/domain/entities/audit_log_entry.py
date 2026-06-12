"""Audit log entry — structured event for post-hoc analysis."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class AuditLogEntry:
    """Single entry in the bot's append-only audit log."""

    bot_run_id: str
    event_type: str
    event_data_json: str
    entry_id: str = field(default_factory=lambda: str(hash(object())))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
