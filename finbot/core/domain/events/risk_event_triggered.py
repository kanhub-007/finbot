"""RiskEventTriggered domain event — raised when a risk gate blocks or stops."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskEventTriggered:
    """Domain event raised when a risk gate blocks an order or stops the bot.

    bot_stopped indicates whether the risk event caused the bot to stop
    (True for daily loss, exchange error, etc.) or just blocked an order
    (False for stale data, duplicate signal, etc.).
    """

    run_id: str
    event_type: str
    reason: str
    bot_stopped: bool
