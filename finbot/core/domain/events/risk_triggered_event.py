"""RiskTriggeredEvent — emitted when a risk gate blocks trading."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskTriggeredEvent:
    """Emitted when a risk gate blocks an order or stops the bot."""

    run_id: str
    event_type: str
    reason: str
    bot_stopped: bool
