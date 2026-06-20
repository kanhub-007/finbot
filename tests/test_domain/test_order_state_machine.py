"""Tests for OrderStateMachine."""

from decimal import Decimal

import pytest

from finbot.core.domain.entities.order_lifecycle import OrderLifecycle
from finbot.core.domain.entities.order_state import OrderState
from finbot.core.domain.services.order_state_machine import (
    InvalidTransitionError,
    OrderStateMachine,
)


class TestValidTransitions:
    def test_planned_to_intent_persisted(self) -> None:
        lifecycle = OrderLifecycle(
            order_id="o1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.001"),
        )
        OrderStateMachine.transition(lifecycle, OrderState.INTENT_PERSISTED)
        assert lifecycle.state == OrderState.INTENT_PERSISTED

    def test_full_lifecycle_to_filled(self) -> None:
        lifecycle = OrderLifecycle(
            order_id="o1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.001"),
        )
        path = [
            OrderState.INTENT_PERSISTED,
            OrderState.SUBMITTED,
            OrderState.ACCEPTED,
            OrderState.OPEN,
            OrderState.FILLED,
        ]
        for state in path:
            OrderStateMachine.transition(lifecycle, state)
        assert lifecycle.state == OrderState.FILLED
        assert lifecycle.filled_size == Decimal("0.001")
        assert lifecycle.remaining_size == Decimal("0")

    def test_partial_fill_updates_remaining_size(self) -> None:
        lifecycle = OrderLifecycle(
            order_id="o1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.01"),
        )
        for s in [
            OrderState.INTENT_PERSISTED,
            OrderState.SUBMITTED,
            OrderState.ACCEPTED,
            OrderState.OPEN,
        ]:
            OrderStateMachine.transition(lifecycle, s)

        # Partial fill of 0.003
        OrderStateMachine.transition(
            lifecycle, OrderState.PARTIALLY_FILLED, reason="0.003",
            fill_size=Decimal("0.003"),
        )
        assert lifecycle.state == OrderState.PARTIALLY_FILLED
        assert lifecycle.filled_size == Decimal("0.003")
        assert lifecycle.remaining_size == Decimal("0.007")

        # Second partial fill
        OrderStateMachine.transition(
            lifecycle, OrderState.PARTIALLY_FILLED, reason="0.002",
            fill_size=Decimal("0.002"),
        )
        assert lifecycle.filled_size == Decimal("0.005")
        assert lifecycle.remaining_size == Decimal("0.005")

    def test_idempotent_same_state_transition(self) -> None:
        lifecycle = OrderLifecycle(
            order_id="o1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.001"),
        )
        OrderStateMachine.transition(lifecycle, OrderState.INTENT_PERSISTED)
        # Same state again — no-op
        OrderStateMachine.transition(lifecycle, OrderState.INTENT_PERSISTED)
        assert lifecycle.state == OrderState.INTENT_PERSISTED


class TestInvalidTransitions:
    def test_invalid_transition_is_rejected(self) -> None:
        lifecycle = OrderLifecycle(
            order_id="o1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.001"),
        )
        with pytest.raises(InvalidTransitionError, match="Cannot transition"):
            OrderStateMachine.transition(lifecycle, OrderState.FILLED)

    def test_terminal_state_blocks_transitions(self) -> None:
        lifecycle = OrderLifecycle(
            order_id="o1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.001"),
        )
        for s in [
            OrderState.INTENT_PERSISTED,
            OrderState.SUBMITTED,
            OrderState.ACCEPTED,
            OrderState.OPEN,
            OrderState.FILLED,
        ]:
            OrderStateMachine.transition(lifecycle, s)

        with pytest.raises(InvalidTransitionError):
            OrderStateMachine.transition(lifecycle, OrderState.OPEN)

    def test_rejected_exchange_response_marks_order_rejected(self) -> None:
        lifecycle = OrderLifecycle(
            order_id="o1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.001"),
        )
        for s in [
            OrderState.INTENT_PERSISTED,
            OrderState.SUBMITTED,
        ]:
            OrderStateMachine.transition(lifecycle, s)

        OrderStateMachine.transition(lifecycle, OrderState.REJECTED)
        assert lifecycle.state == OrderState.REJECTED
        assert OrderStateMachine.is_terminal(lifecycle.state)


class TestReconciliation:
    def test_reconciliation_from_open_to_unknown(self) -> None:
        lifecycle = OrderLifecycle(
            order_id="o1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.001"),
        )
        for s in [
            OrderState.INTENT_PERSISTED,
            OrderState.SUBMITTED,
            OrderState.ACCEPTED,
            OrderState.OPEN,
        ]:
            OrderStateMachine.transition(lifecycle, s)

        OrderStateMachine.transition(
            lifecycle,
            OrderState.UNKNOWN_RECONCILE_REQUIRED,
            reason="position mismatch",
        )
        assert lifecycle.state == OrderState.UNKNOWN_RECONCILE_REQUIRED

    def test_unknown_reconciliation_blocks_new_orders(self) -> None:
        lifecycle = OrderLifecycle(
            order_id="o1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.001"),
        )
        OrderStateMachine.transition(lifecycle, OrderState.INTENT_PERSISTED)
        OrderStateMachine.transition(lifecycle, OrderState.SUBMITTED)
        OrderStateMachine.transition(
            lifecycle,
            OrderState.UNKNOWN_RECONCILE_REQUIRED,
        )
        assert OrderStateMachine.blocks_new_orders(lifecycle.state)

    def test_cannot_reconcile_from_terminal(self) -> None:
        lifecycle = OrderLifecycle(
            order_id="o1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.001"),
        )
        for s in [
            OrderState.INTENT_PERSISTED,
            OrderState.SUBMITTED,
            OrderState.ACCEPTED,
            OrderState.OPEN,
            OrderState.FILLED,
        ]:
            OrderStateMachine.transition(lifecycle, s)

        with pytest.raises(InvalidTransitionError, match="reconcile"):
            OrderStateMachine.transition(
                lifecycle, OrderState.UNKNOWN_RECONCILE_REQUIRED
            )

    def test_cannot_reconcile_from_pre_exchange(self) -> None:
        lifecycle = OrderLifecycle(
            order_id="o1",
            symbol="BTC",
            side="buy",
            original_size=Decimal("0.001"),
        )
        OrderStateMachine.transition(lifecycle, OrderState.INTENT_PERSISTED)
        with pytest.raises(InvalidTransitionError, match="pre-exchange"):
            OrderStateMachine.transition(
                lifecycle, OrderState.UNKNOWN_RECONCILE_REQUIRED
            )
