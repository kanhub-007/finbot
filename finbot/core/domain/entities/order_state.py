"""Order state enum — all states in the order lifecycle."""

from enum import StrEnum


class OrderState(StrEnum):
    """Order lifecycle states for the state machine."""

    PLANNED = "planned"
    RISK_REJECTED = "risk_rejected"
    INTENT_PERSISTED = "intent_persisted"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN_RECONCILE_REQUIRED = "unknown_reconcile_required"


#: States where the order is still considered "live" on the exchange.
#: Used by reconciliation to detect local lifecycles the exchange no
#: longer reports (stale rows after a crash/restart).
ACTIVE_ORDER_STATES: frozenset[OrderState] = frozenset(
    {
        OrderState.SUBMITTED,
        OrderState.ACCEPTED,
        OrderState.OPEN,
        OrderState.PARTIALLY_FILLED,
        OrderState.CANCEL_REQUESTED,
    }
)
