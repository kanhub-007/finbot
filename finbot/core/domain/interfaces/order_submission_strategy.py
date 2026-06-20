"""OrderSubmissionStrategy — domain interface for mode-specific order submission."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from finbot.core.domain.entities.order_intent import OrderIntent


class OrderSubmissionStrategy(ABC):
    """Strategy for submitting orders based on trading mode.

    Dry-run mode synthesizes fills without exchange calls.
    Testnet/live modes submit real orders via the exchange gateway.

    Each strategy is responsible for recording the order intent
    and dispatching appropriately.
    """

    @abstractmethod
    def submit(
        self,
        intent: OrderIntent,
        bot_run_id: str,
        latest_bar: dict[str, Any] | None,
    ) -> tuple[str, bool]:
        """Record and submit an order intent.

        Args:
            intent: The OrderIntent to submit (with cloid already set).
            bot_run_id: The current bot run identifier.
            latest_bar: Most recent candle for price reference.

        Returns:
            A tuple of (intent_id, was_submitted). intent_id is the
            repository-generated ID. was_submitted is True when the order
            was sent to the exchange (testnet/live), False for dry-run.
        """
        ...
