"""Result of enrichment validation for a single enriched bar.

Pure domain entity — no framework dependencies.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EnrichmentValidationResult:
    """Gate result before strategy evaluation.

    When ``valid`` is False the strategy must not be evaluated
    and no order intent must be planned.
    """

    valid: bool
    """Whether the enriched bar is safe to evaluate."""

    missing_columns: list[str] = field(default_factory=list)
    """Required strategy columns that are absent from the enriched bar."""

    non_finite_columns: list[str] = field(default_factory=list)
    """Required columns whose latest value is None, NaN, inf, or -inf."""

    invalid_type_columns: list[str] = field(default_factory=list)
    """Required columns whose latest value has an incompatible type."""

    reason: str = ""
    """Human-readable explanation of the rejection (empty when valid)."""
