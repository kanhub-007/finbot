"""TelegramChat domain entity — an authorized chat subscribed to notifications."""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class TelegramChat:
    """Represents an authorized Telegram chat registered for bot interaction.

    Each chat is identified by its chat_id. The user_id links it to the
    Telegram user who registered. notifications_enabled controls whether
    proactive notifications (trades, risk events) are sent to this chat.
    """

    chat_id: int
    user_id: int
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notifications_enabled: bool = True
