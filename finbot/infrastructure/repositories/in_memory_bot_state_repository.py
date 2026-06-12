"""In-memory bot state repository for early dry-run development."""

from typing import Any
from uuid import uuid4

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.interfaces.bot_state_repository import BotStateRepository


class InMemoryBotStateRepository(BotStateRepository):
    """Stores bot state in process memory for tests and dry-run skeletons."""

    def __init__(self):
        self._responses: dict[str, dict[str, Any]] = {}
        self._processed_signals: set[str] = set()

    def record_order_intent(self, intent: OrderIntent) -> str:
        """Persist an order intent and return its generated id."""
        intent_id = str(uuid4())
        self._responses[intent_id] = {"intent": intent}
        return intent_id

    def record_order_response(self, intent_id: str, response: dict[str, Any]) -> None:
        """Persist the exchange response for an order intent."""
        self._responses.setdefault(intent_id, {})["response"] = response

    def has_processed_signal(self, signal_key: str) -> bool:
        """Return whether a signal key has already been processed."""
        return signal_key in self._processed_signals

    def mark_signal_processed(self, signal_key: str) -> None:
        """Mark a signal key as processed."""
        self._processed_signals.add(signal_key)
