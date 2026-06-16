"""TelegramCommand — immutable parsed command value object."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TelegramCommand:
    """Immutable value object representing a parsed Telegram command.

    Extracted from a Telegram message update before being passed
    to the application layer.
    """

    command: str
    args: str
    chat_id: int
    user_id: int
    message_id: int
    timestamp: datetime
