"""Bot event type enum."""

from enum import StrEnum


class BotEventType(StrEnum):
    CANDLE = "candle"
    ORDER_UPDATE = "order_update"
    FILL = "fill"
    STALE = "stale"
    SHUTDOWN = "shutdown"
