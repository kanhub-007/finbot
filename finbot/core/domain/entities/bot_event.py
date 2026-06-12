"""Bot event — typed envelope for events flowing through the bot loop."""

from dataclasses import dataclass, field
from typing import Any

from finbot.core.domain.entities.bot_event_type import BotEventType


@dataclass(frozen=True)
class BotEvent:
    """A single event produced by the market data stream or risk checker.

    Parameters
    ----------
    type:
        Event category (candle, order_update, fill, stale, shutdown).
    data:
        Event payload — a bar dict for candles, order dict for
        order updates, fill dict for fills, etc.
    """

    type: BotEventType
    data: dict[str, Any] = field(default_factory=dict)
