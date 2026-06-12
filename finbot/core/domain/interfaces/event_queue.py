"""Event queue interface — thread-safe boundary for bot events."""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.bot_event import BotEvent


class EventQueue(ABC):
    """Bounded, thread-safe queue for bot events.

    SDK callbacks running on websocket threads enqueue events here;
    the main bot loop dequeues and processes them sequentially.
    """

    @abstractmethod
    def enqueue(self, event: BotEvent) -> bool:
        """Push an event onto the queue.

        Returns True if the event was accepted, False if the queue
        is full (backpressure — caller decides policy).
        """

    @abstractmethod
    def dequeue(self, timeout: float | None = None) -> BotEvent | None:
        """Remove and return the next event, or None on timeout.

        Blocks up to ``timeout`` seconds.  None means block
        indefinitely.
        """

    @abstractmethod
    def size(self) -> int:
        """Number of events currently in the queue."""

    @abstractmethod
    def clear(self) -> None:
        """Discard all pending events (used during shutdown flush)."""
