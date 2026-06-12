"""Strategy snapshot — frozen copy of the strategy YAML at runtime."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True)
class StrategySnapshot:
    """Immutable record of the strategy definition used during a bot run.

    Stored once per bot run so that historical signals can be re-validated
    against the exact strategy that produced them.
    """

    bot_run_id: str
    strategy_hash: str
    full_yaml: str
    snapshot_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
