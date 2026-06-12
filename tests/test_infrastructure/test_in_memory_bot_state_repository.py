"""Tests for InMemoryBotStateRepository."""

from decimal import Decimal

import pytest

from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
    InMemoryBotStateRepository,
)


class TestInMemoryBotStateRepository:
    def setup_method(self) -> None:
        self.repo = InMemoryBotStateRepository()

    def test_record_order_intent_returns_id(self) -> None:
        intent = OrderIntent(
            symbol="BTC",
            side=OrderSide.BUY,
            size=Decimal("0.001"),
            order_type=OrderType.LIMIT,
        )
        intent_id = self.repo.record_order_intent(intent)
        assert isinstance(intent_id, str)
        assert len(intent_id) > 0

    def test_record_order_response_requires_prior_intent(self) -> None:
        with pytest.raises(KeyError, match="Unknown intent_id"):
            self.repo.record_order_response("nonexistent", {"status": "filled"})

    def test_signal_key_idempotency(self) -> None:
        assert self.repo.has_processed_signal("sig1") is False
        self.repo.mark_signal_processed("sig1")
        assert self.repo.has_processed_signal("sig1") is True
        # Second mark should be harmless.
        self.repo.mark_signal_processed("sig1")
        assert self.repo.has_processed_signal("sig1") is True
