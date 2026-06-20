"""Tests for OrderStateMachine explicit fill_size (S14: M1)."""

from decimal import Decimal

from finbot.core.domain.entities.order_lifecycle import OrderLifecycle
from finbot.core.domain.entities.order_state import OrderState
from finbot.core.domain.services.order_state_machine import OrderStateMachine


class TestFillSizeParam:
    def test_partial_fill_increments_via_explicit_param(self):
        lc = OrderLifecycle(
            order_id="o", symbol="BTC", side="buy", original_size=Decimal("1")
        )
        OrderStateMachine.transition(lc, OrderState.INTENT_PERSISTED)
        OrderStateMachine.transition(lc, OrderState.SUBMITTED)
        OrderStateMachine.transition(lc, OrderState.ACCEPTED)
        OrderStateMachine.transition(lc, OrderState.OPEN)
        OrderStateMachine.transition(
            lc, OrderState.PARTIALLY_FILLED, reason="fill 1", fill_size=Decimal("0.3")
        )
        assert lc.filled_size == Decimal("0.3")
        OrderStateMachine.transition(
            lc, OrderState.PARTIALLY_FILLED, reason="fill 2", fill_size=Decimal("0.4")
        )
        assert lc.filled_size == Decimal("0.7")

    def test_reason_string_no_longer_parsed_for_size(self):
        """A non-numeric reason must not break the transition."""
        lc = OrderLifecycle(
            order_id="o", symbol="BTC", side="buy", original_size=Decimal("1")
        )
        OrderStateMachine.transition(lc, OrderState.INTENT_PERSISTED)
        OrderStateMachine.transition(lc, OrderState.SUBMITTED)
        OrderStateMachine.transition(lc, OrderState.ACCEPTED)
        OrderStateMachine.transition(lc, OrderState.OPEN)
        OrderStateMachine.transition(
            lc,
            OrderState.PARTIALLY_FILLED,
            reason="user cancelled trigger",
            fill_size=Decimal("0.5"),
        )
        assert lc.filled_size == Decimal("0.5")
