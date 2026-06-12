"""Order plan result DTO — outcome of the order planning pipeline."""

from dataclasses import dataclass

from finbot.core.domain.entities.order_intent import OrderIntent


@dataclass(frozen=True)
class OrderPlanResult:
    """Result of planning an order from a strategy signal.

    Parameters
    ----------
    accepted:
        True when all risk gates passed.
    reason:
        Human-readable reason when rejected.
    gate_name:
        Name of the rejecting gate, if any.
    intent:
        Proposed order intent (None when rejected).
    signal_key:
        Signal key that triggered this plan.
    """

    accepted: bool
    reason: str = ""
    gate_name: str = ""
    intent: OrderIntent | None = None
    signal_key: str = ""
