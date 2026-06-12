"""Thread-safe event queue backed by queue.Queue."""

from __future__ import annotations

import queue

from finbot.core.application.dto.bot_event import BotEvent
from finbot.core.domain.interfaces.event_queue import EventQueue


class ThreadSafeEventQueue(EventQueue):
    """Bounded, thread-safe queue using the standard library.

    Parameters
    ----------
    maxsize:
        Maximum number of events before backpressure.  0 = unbounded.
    """

    def __init__(self, maxsize: int = 1024) -> None:
        self._q: queue.Queue[BotEvent] = queue.Queue(maxsize=maxsize)

    def enqueue(self, event: BotEvent) -> bool:
        try:
            self._q.put_nowait(event)
            return True
        except queue.Full:
            return False

    def dequeue(self, timeout: float | None = None) -> BotEvent | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def size(self) -> int:
        return self._q.qsize()

    def clear(self) -> None:
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
