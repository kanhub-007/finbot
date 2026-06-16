"""Thread-safe event queue backed by queue.Queue."""

from __future__ import annotations

import queue
import threading

from finbot.core.domain.entities.bot_event import BotEvent
from finbot.core.domain.entities.bot_event_type import BotEventType
from finbot.core.domain.interfaces.event_queue import EventQueue

# Events whose latency matters (fills / order updates) — the dispatch loop
# prioritises these ahead of queued candles.
_ACCOUNT_EVENT_TYPES = frozenset({BotEventType.FILL, BotEventType.ORDER_UPDATE})


def _is_account_event(event: BotEvent) -> bool:
    return event.type in _ACCOUNT_EVENT_TYPES


class ThreadSafeEventQueue(EventQueue):
    """Bounded, thread-safe queue using the standard library.

    Parameters
    ----------
    maxsize:
        Maximum number of events before backpressure.  0 = unbounded.
    """

    def __init__(self, maxsize: int = 1024) -> None:
        self._q: queue.Queue[BotEvent] = queue.Queue(maxsize=maxsize)
        # Pending account-event count, maintained only for account events so
        # the common candle enqueue/dequeue pays just a type check (no lock).
        self._account_pending = 0
        self._account_lock = threading.Lock()

    def enqueue(self, event: BotEvent) -> bool:
        try:
            self._q.put_nowait(event)
        except queue.Full:
            return False
        if _is_account_event(event):
            with self._account_lock:
                self._account_pending += 1
        return True

    def dequeue(self, timeout: float | None = None) -> BotEvent | None:
        try:
            event = self._q.get(timeout=timeout)
        except queue.Empty:
            return None
        if _is_account_event(event):
            with self._account_lock:
                self._account_pending -= 1
        return event

    def size(self) -> int:
        return self._q.qsize()

    def account_event_count(self) -> int:
        with self._account_lock:
            return self._account_pending

    def clear(self) -> None:
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        with self._account_lock:
            self._account_pending = 0
