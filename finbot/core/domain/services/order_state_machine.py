"""Order state machine — validates and applies lifecycle transitions."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from finbot.core.domain.entities.order_lifecycle import OrderLifecycle
from finbot.core.domain.entities.order_state import OrderState


class InvalidTransitionError(ValueError):
    """Raised when a state transition is not allowed."""


class OrderStateMachine:
    """Validates and applies state transitions for an :class:`OrderLifecycle`.

    Transitions not in ``ALLOWED`` are rejected.  Terminal states
    (FILLED, CANCELLED, REJECTED, EXPIRED) accept no further
    transitions.  The ``UNKNOWN_RECONCILE_REQUIRED`` state can be
    reached from any non-terminal state during reconciliation.
    """

    ALLOWED: ClassVar[dict[OrderState, set[OrderState]]] = {
        OrderState.PLANNED: {OrderState.RISK_REJECTED, OrderState.INTENT_PERSISTED},
        OrderState.RISK_REJECTED: set(),
        OrderState.INTENT_PERSISTED: {OrderState.SUBMITTED},
        OrderState.SUBMITTED: {OrderState.ACCEPTED, OrderState.REJECTED},
        OrderState.ACCEPTED: {OrderState.OPEN},
        OrderState.OPEN: {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_REQUESTED,
        },
        OrderState.PARTIALLY_FILLED: {
            OrderState.PARTIALLY_FILLED,  # idempotent partial fill
            OrderState.FILLED,
            OrderState.CANCEL_REQUESTED,
        },
        OrderState.FILLED: set(),
        OrderState.CANCEL_REQUESTED: {OrderState.CANCELLED},
        OrderState.CANCELLED: set(),
        OrderState.REJECTED: set(),
        OrderState.EXPIRED: set(),
        OrderState.UNKNOWN_RECONCILE_REQUIRED: set(),
    }

    # States that block new order placement.
    BLOCKING: ClassVar[set[OrderState]] = {
        OrderState.UNKNOWN_RECONCILE_REQUIRED,
    }

    TERMINAL: ClassVar[set[OrderState]] = {
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
        OrderState.RISK_REJECTED,
    }

    # -- public API --------------------------------------------------------

    @classmethod
    def can_transition(cls, from_state: OrderState, to_state: OrderState) -> bool:
        allowed = cls.ALLOWED.get(from_state, set())
        return to_state in allowed

    @classmethod
    def blocks_new_orders(cls, state: OrderState) -> bool:
        return state in cls.BLOCKING

    @classmethod
    def is_terminal(cls, state: OrderState) -> bool:
        return state in cls.TERMINAL

    @classmethod
    def transition(
        cls,
        lifecycle: OrderLifecycle,
        to_state: OrderState,
        reason: str = "",
    ) -> None:
        """Move *lifecycle* to *to_state*, raising on invalid transitions.

        Reconciliation from any non-terminal state to
        ``UNKNOWN_RECONCILE_REQUIRED`` is always permitted.
        """
        current = lifecycle.state

        if current == to_state:
            # Allow same-state transitions for partial fills
            # since each one carries a new fill size in the reason.
            if to_state == OrderState.PARTIALLY_FILLED:
                cls._update_sizes(lifecycle, to_state, reason)
                return
            # All other same-state transitions are true idempotent no-ops.
            return

        # Reconciliation escape hatch.
        if to_state == OrderState.UNKNOWN_RECONCILE_REQUIRED:
            if not cls.is_terminal(current):
                lifecycle.record_transition(current, to_state, reason)
                lifecycle.state = to_state
                return
            raise InvalidTransitionError(
                f"Cannot reconcile from terminal state {current.value}"
            )

        if not cls.can_transition(current, to_state):
            raise InvalidTransitionError(
                f"Cannot transition {current.value} → {to_state.value}"
            )

        lifecycle.record_transition(current, to_state, reason)
        lifecycle.state = to_state
        cls._update_sizes(lifecycle, to_state, reason)

    # -- internal -----------------------------------------------------------

    @classmethod
    def _update_sizes(
        cls,
        lifecycle: OrderLifecycle,
        to_state: OrderState,
        reason: str,
    ) -> None:
        if to_state == OrderState.PARTIALLY_FILLED and reason:
            try:
                filled = Decimal(reason)
                lifecycle.filled_size += filled
                lifecycle.remaining_size = max(
                    Decimal("0"),
                    lifecycle.original_size - lifecycle.filled_size,
                )
            except Exception:
                pass
        elif to_state == OrderState.FILLED:
            lifecycle.filled_size = lifecycle.original_size
            lifecycle.remaining_size = Decimal("0")
