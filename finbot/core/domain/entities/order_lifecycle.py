"""Order lifecycle entity — tracks an order through its state machine."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from finbot.core.domain.entities.order_state import OrderState


@dataclass
class OrderLifecycle:
    """Mutable entity tracking an order from planning to final state.

    Not frozen — the state and remaining size change as the order
    progresses through fills and cancellations.
    """

    order_id: str
    symbol: str
    side: str
    original_size: Decimal
    state: OrderState = OrderState.PLANNED
    remaining_size: Decimal = Decimal("0")
    filled_size: Decimal = Decimal("0")
    transition_history: list[tuple[OrderState, OrderState, str]] = field(
        default_factory=list
    )
    # Number of transitions already persisted by the repository.  Tracked on
    # the entity so a repository can save only the *new* transitions on each
    # save rather than re-inserting the whole history (O(k) instead of O(k²)).
    persisted_transition_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        # This dataclass is intentionally mutable (the state machine updates
        # ``state``/``filled_size``/``remaining_size`` in place), so plain
        # assignment is correct here — no need for the frozen-dataclass
        # ``object.__setattr__`` escape hatch.
        if self.remaining_size == Decimal("0"):
            self.remaining_size = self.original_size

    def record_transition(
        self, from_state: OrderState, to_state: OrderState, reason: str = ""
    ) -> None:
        self.transition_history.append((from_state, to_state, reason))

    @property
    def unpersisted_transitions(
        self,
    ) -> list[tuple[OrderState, OrderState, str]]:
        """Transitions added since the last successful repository save."""
        return self.transition_history[self.persisted_transition_count :]
