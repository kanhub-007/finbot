"""SendResult — result value object for Telegram send/edit operations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SendResult:
    """Result of attempting to send or edit a Telegram message.

    success: whether the operation completed without error.
    message_id: the Telegram message ID if successful (None on failure).
    error: error description if the operation failed.
    transient: True if the error may succeed on retry (e.g. rate limit,
        network timeout). False for permanent errors (e.g. chat not found,
        bot blocked).
    """

    success: bool
    message_id: int | None = None
    error: str | None = None
    transient: bool = False
