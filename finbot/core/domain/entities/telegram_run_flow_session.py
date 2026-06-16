"""TelegramRunFlowSession — stores /run guided-flow state server-side."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class TelegramRunFlowSession:
    """Server-side session for the multi-step /run guided flow.

    Stores accumulated selections (strategy, symbol, interval, mode)
    so callback_data can stay under Telegram's 64-byte limit.
    The session_id is a short string used in callback payloads.
    """

    session_id: str
    chat_id: int
    message_id: int
    strategy_path: str | None = None
    symbol: str | None = None
    interval: str | None = None
    mode: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=30)
    )

    @property
    def is_expired(self, now: datetime | None = None) -> bool:
        """Check if the session has expired."""
        now = now or datetime.now(timezone.utc)
        return now > self.expires_at
