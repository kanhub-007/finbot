"""Bot state repository interface."""

from abc import ABC, abstractmethod
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent


class BotStateRepository(ABC):
    """Persists bot signals, intents, orders, fills, and audit events."""

    @abstractmethod
    def record_order_intent(self, intent: OrderIntent) -> str:
        """Persist an order intent before exchange submission."""

    @abstractmethod
    def record_order_response(self, intent_id: str, response: dict[str, Any]) -> None:
        """Persist the exchange response for an order intent."""

    @abstractmethod
    def has_processed_signal(self, signal_key: str) -> bool:
        """Return whether a signal key has already been processed."""

    @abstractmethod
    def mark_signal_processed(self, signal_key: str) -> None:
        """Mark a signal key as processed to prevent duplicate orders."""
