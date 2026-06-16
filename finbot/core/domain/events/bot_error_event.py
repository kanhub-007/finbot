"""BotErrorEvent domain event — raised on unrecoverable runtime errors."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BotErrorEvent:
    """Domain event raised when the trading runtime hits an unrecoverable error.

    Notifications are fire-and-forget; the error is also logged and may
    be persisted via the repository.
    """

    run_id: str
    error_type: str
    message: str
