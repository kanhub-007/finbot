"""Order response record — exchange response for a submitted order."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True)
class OrderResponseRecord:
    """Exchange response captured after an order intent is submitted.

    Linked to the original ``OrderIntent`` via ``intent_id``.
    """

    intent_id: str
    bot_run_id: str
    response_json: str
    status: str  # accepted / rejected / expired / unknown
    response_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
