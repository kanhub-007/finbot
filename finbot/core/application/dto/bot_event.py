"""Bot event DTO — typed event envelope for the bot event loop.

All events flowing through the bot are wrapped in this envelope so
the event loop can dispatch them uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BotEventType(StrEnum):
    CANDLE = "candle"
    ORDER_UPDATE = "order_update"
    FILL = "fill"
    STALE = "stale"
    SHUTDOWN = "shutdown"


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
