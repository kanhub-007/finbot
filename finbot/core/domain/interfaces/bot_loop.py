"""Bot loop interface — domain abstraction for the main event loop."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class BotLoop(ABC):
    """Main event loop contract — abstracts blocking event processing.

    Implementations wrap websocket message pumps, thread-safe queues,
    and reconnection logic.  The application layer depends on this
    interface so it never imports infrastructure-level event loops.
    """

    @abstractmethod
    def start(
        self,
        symbol: str,
        interval: str,
        on_candle: Callable[[dict[str, Any]], object],
        on_stale: Callable[[dict[str, Any]], object] | None = None,
    ) -> None:
        """Block the calling thread and process events until stopped."""

    @abstractmethod
    def stop(self) -> None:
        """Signal the event loop to shut down gracefully."""
