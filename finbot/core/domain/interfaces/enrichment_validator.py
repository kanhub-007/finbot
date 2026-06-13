"""Enrichment validator interface — pure domain contract.

Implementations check whether an enriched bar is safe to pass to
a strategy evaluator.
"""

from abc import ABC, abstractmethod
from typing import Any

from finbot.core.domain.entities.enrichment_validation_result import (
    EnrichmentValidationResult,
)


class EnrichmentValidator(ABC):
    """Validate enriched bar quality before strategy evaluation."""

    @abstractmethod
    def validate(
        self,
        enriched_bar: dict[str, Any],
        required_columns: set[str],
        warmup_ready: bool,
        has_gap: bool,
    ) -> EnrichmentValidationResult:
        """Return a structured validation result for one enriched bar.

        Args:
            enriched_bar: Latest enriched bar dict with indicator columns.
            required_columns: Set of column names the strategy requires.
            warmup_ready: True when the warmup window has enough bars.
            has_gap: True when a gap was detected in the warmup window.

        Returns:
            An ``EnrichmentValidationResult`` — ``valid=True`` iff the bar
            is safe for strategy evaluation.
        """
