"""SimpleRuntimeEventEmitter — in-process synchronous observer dispatcher."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from finbot.core.domain.interfaces.runtime_event_emitter import (
    RuntimeEventEmitter,
)


class SimpleRuntimeEventEmitter(RuntimeEventEmitter):
    """Synchronous, in-process event emitter.

    Observers are called immediately in the calling thread.
    For cross-thread dispatch (e.g. Telegram), the observer itself
    handles the thread boundary (e.g. via run_coroutine_threadsafe).
    """

    def __init__(self) -> None:
        self._observers: dict[type, list[Any]] = defaultdict(list)

    def subscribe(self, event_type: type, observer: Any) -> None:
        """Register an observer for a specific event type."""
        self._observers[event_type].append(observer)

    def emit(self, event: Any) -> None:
        """Call all observers registered for this event's type."""
        event_type = type(event)
        for observer in self._observers.get(event_type, []):
            try:
                observer(event)
            except Exception:
                pass  # Fire-and-forget — observer failures don't block pipeline
