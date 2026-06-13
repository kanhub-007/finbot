"""Enrichment quality gate — pure domain service.

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
from finbot.core.domain.interfaces.enrichment_validator import (
    EnrichmentValidator as EnrichmentValidatorInterface,
)


class EnrichmentValidator(EnrichmentValidatorInterface):
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
        if not warmup_ready:
            return EnrichmentValidationResult(
                valid=False, reason="warmup window is not ready"
            )
        if has_gap:
            return EnrichmentValidationResult(
                valid=False, reason="warmup window has gaps"
            )
        return self._check_columns(enriched_bar, required_columns)

    # -- internal -----------------------------------------------------------

    def _check_columns(
        self,
        enriched_bar: dict[str, Any],
        required_columns: set[str],
    ) -> EnrichmentValidationResult:
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

            if isinstance(value, str):
                bad_type.append(col)

        return self._build_result(missing, non_finite, bad_type)

    @staticmethod
    def _build_result(
        missing: list[str],
        non_finite: list[str],
        bad_type: list[str],
    ) -> EnrichmentValidationResult:
        if not (missing or non_finite or bad_type):
            return EnrichmentValidationResult(valid=True)

        parts: list[str] = []
        if missing:
            parts.append(f"missing columns: {', '.join(missing)}")
        if non_finite:
            parts.append(f"non-finite values: {', '.join(non_finite)}")
        if bad_type:
            parts.append(f"invalid type columns: {', '.join(bad_type)}")

        return EnrichmentValidationResult(
            valid=False,
            missing_columns=missing,
            non_finite_columns=non_finite,
            invalid_type_columns=bad_type,
            reason="; ".join(parts),
        )
