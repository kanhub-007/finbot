"""Processed signal — a signal key that has been acted upon."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class ProcessedSignal:
    """Record that a signal key was processed to prevent duplicates."""

    signal_key: str
    bot_run_id: str
    signal_action: str
    bar_timestamp: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
