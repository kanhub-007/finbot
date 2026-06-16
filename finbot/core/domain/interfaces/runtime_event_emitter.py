"""RuntimeEventEmitter — domain interface for emitting runtime events."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RuntimeEventEmitter(ABC):
    """Emits events during the trading pipeline.

    Observers subscribe to specific event types. The runtime calls
    ``emit()`` without knowing what observers do with the events.
    This decouples notification logic (Telegram, logging, metrics)
    from the trading pipeline.
    """

    @abstractmethod
    def subscribe(self, event_type: type, observer: Any) -> None:
        """Register an observer for a specific event type.

        The observer must be a callable accepting one argument (the event).
        """
        ...

    @abstractmethod
    def emit(self, event: Any) -> None:
        """Emit an event to all registered observers of its type."""
        ...
