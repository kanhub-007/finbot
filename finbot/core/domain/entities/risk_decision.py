"""Risk decision — outcome of a single risk gate evaluation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskDecision:
    """Result of evaluating a risk gate against a signal.

    Parameters
    ----------
    accepted:
        True when the signal passes this gate.
    reason:
        Human-readable reason when rejected.
    gate_name:
        Name of the gate that produced this decision (for audit).
    """

    accepted: bool
    reason: str = ""
    gate_name: str = ""
