"""StrategyValidationResult entity for JSON validation."""

from dataclasses import dataclass, field

from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)


@dataclass(frozen=True)
class StrategyValidationResult:
    """Structured validation result for an agent-authored strategy."""

    valid: bool
    """True when the strategy parsed and passed semantic validation."""

    errors: list[StrategyValidationError] = field(default_factory=list)
    """Path-specific validation errors."""

    warnings: list[StrategyValidationError] = field(default_factory=list)
    """Path-specific non-fatal warnings."""

    definition: StrategyDefinition | None = None
    """Canonical strategy definition when valid."""

    required_indicators: list[str] = field(default_factory=list)
    """Concrete indicator columns requested by declared indicator aliases."""

    required_columns: list[str] = field(default_factory=list)
    """Concrete bar columns required to execute the strategy."""

    primary_required_indicators: list[str] = field(default_factory=list)
    """Concrete indicators that must be calculated on primary bars."""

    informative_required_indicators: dict[str, list[str]] = field(default_factory=dict)
    """Concrete indicators that must be calculated on each informative alias."""

    timeframe_intervals: dict[str, str] = field(default_factory=dict)
    """Timeframe alias to interval mapping used by the strategy."""

    missing_columns: list[str] = field(default_factory=list)
    """Required bar columns missing from a supplied enriched dataset."""

    normalized: dict = field(default_factory=dict)
    """Canonical normalized JSON representation of the parsed definition."""
