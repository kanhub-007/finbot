"""StrategyValidationError entity for JSON diagnostics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyValidationError:
    """A path-specific validation diagnostic for an agent-authored strategy."""

    path: str
    """JSONPath-like location of the problem."""

    message: str
    """Human-readable diagnostic message."""

    code: str = "validation_error"
    """Stable machine-readable error code."""
