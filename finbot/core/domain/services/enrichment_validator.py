"""Enrichment validator — pure domain service that gates strategy evaluation.

Checks that an enriched bar is safe to pass to a strategy evaluator:
required columns present, latest values finite, valid types, warmup
ready, no gap.
"""

from __future__ import annotations

from math import isfinite, isnan
from typing import Any

from finbot.core.domain.entities.enrichment_validation_result import (
    EnrichmentValidationResult,
)


class EnrichmentValidator:
    """Validates enriched bar quality before strategy evaluation.

    This is a pure domain service with no I/O or framework dependencies.
    It inspects the enriched bar dictionary and the warmup/gap flags
    and returns a structured validation result.
    """

    def validate(
        self,
        enriched_bar: dict[str, Any],
        required_columns: set[str],
        warmup_ready: bool,
        has_gap: bool,
    ) -> EnrichmentValidationResult:
        """Validate the latest enriched bar against strategy requirements.

        Args:
            enriched_bar: Latest enriched bar dict with indicator columns.
            required_columns: Set of column names the strategy requires.
            warmup_ready: True when the warmup window has enough bars.
            has_gap: True when a gap was detected in the warmup window.

        Returns:
            An ``EnrichmentValidationResult`` describing whether the bar
            is safe for strategy evaluation and, if not, why.
        """
        if not warmup_ready:
            return EnrichmentValidationResult(
                valid=False,
                reason="warmup window is not ready",
            )
        if has_gap:
            return EnrichmentValidationResult(
                valid=False,
                reason="warmup window has gaps",
            )

        missing: list[str] = []
        non_finite: list[str] = []
        bad_type: list[str] = []

        for col in sorted(required_columns):
            if col not in enriched_bar:
                missing.append(col)
                continue

            value = enriched_bar[col]

            if value is None:
                non_finite.append(col)
                continue

            if isinstance(value, bool):
                continue

            if isinstance(value, (int, float)):
                if isnan(value) or not isfinite(value):
                    non_finite.append(col)
                continue

            # String, dict, list, etc. — may be acceptable depending
            # on strategy expectations.  Strings that cannot be parsed
            # as numbers or booleans are flagged.
            if isinstance(value, str):
                bad_type.append(col)
            # Other non-primitive types are accepted for now as the
            # strategy evaluator is responsible for interpreting them.

        if missing or non_finite or bad_type:
            parts: list[str] = []
            if missing:
                parts.append(f"missing columns: {', '.join(missing)}")
            if non_finite:
                parts.append(
                    f"non-finite values: {', '.join(non_finite)}"
                )
            if bad_type:
                parts.append(
                    f"invalid type columns: {', '.join(bad_type)}"
                )
            return EnrichmentValidationResult(
                valid=False,
                missing_columns=missing,
                non_finite_columns=non_finite,
                invalid_type_columns=bad_type,
                reason="; ".join(parts),
            )

        return EnrichmentValidationResult(valid=True)
