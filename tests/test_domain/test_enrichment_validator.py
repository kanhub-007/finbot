"""Tests for EnrichmentValidator — the enrichment quality gate."""

import math

import pytest

from finbot.core.domain.entities.enrichment_validation_result import (
    EnrichmentValidationResult,
)
from finbot.core.domain.services.enrichment_validator import EnrichmentValidator


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _bar(**fields: object) -> dict:
    """Build a synthetic enriched bar dict for tests."""
    return dict(fields)


# ---------------------------------------------------------------------------
# Valid bars pass
# ---------------------------------------------------------------------------

def test_valid_bar_passes_all_checks() -> None:
    validator = EnrichmentValidator()
    bar = _bar(
        close=50500.0,
        atr=1200.0,
        vp_vah=52000.0,
        vp_val=50000.0,
        acceptance_into_value=True,
    )
    required = {"atr", "vp_vah", "vp_val", "acceptance_into_value"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=False,
    )

    assert result.valid is True
    assert result.missing_columns == []
    assert result.non_finite_columns == []
    assert result.invalid_type_columns == []
    assert result.reason == ""


# ---------------------------------------------------------------------------
# Missing required columns
# ---------------------------------------------------------------------------

def test_missing_required_column_rejects() -> None:
    validator = EnrichmentValidator()
    bar = _bar(close=50000.0, atr=10.0)
    required = {"atr", "vp_vah", "vp_val"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=False,
    )

    assert result.valid is False
    assert "vp_vah" in result.missing_columns
    assert "vp_val" in result.missing_columns
    assert "atr" not in result.missing_columns


def test_all_required_columns_missing_rejects() -> None:
    validator = EnrichmentValidator()
    bar = _bar(close=50000.0)
    required = {"atr", "vp_vah"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=False,
    )

    assert result.valid is False
    assert set(result.missing_columns) == {"atr", "vp_vah"}


# ---------------------------------------------------------------------------
# Non-finite numeric values
# ---------------------------------------------------------------------------

def test_nan_in_required_numeric_column_rejects() -> None:
    validator = EnrichmentValidator()
    bar = _bar(
        close=50500.0,
        atr=float("nan"),
        vp_vah=52000.0,
        vp_val=50000.0,
        acceptance_into_value=True,
    )
    required = {"atr", "vp_vah", "vp_val", "acceptance_into_value"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=False,
    )

    assert result.valid is False
    assert "atr" in result.non_finite_columns
    assert result.reason != ""


def test_inf_in_required_numeric_column_rejects() -> None:
    validator = EnrichmentValidator()
    bar = _bar(
        close=50500.0,
        atr=float("inf"),
        vp_vah=52000.0,
        vp_val=50000.0,
        acceptance_into_value=True,
    )
    required = {"atr", "vp_vah", "vp_val", "acceptance_into_value"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=False,
    )

    assert result.valid is False
    assert "atr" in result.non_finite_columns


def test_negative_inf_in_required_numeric_column_rejects() -> None:
    validator = EnrichmentValidator()
    bar = _bar(
        close=50500.0,
        atr=float("-inf"),
        vp_vah=52000.0,
        vp_val=50000.0,
        acceptance_into_value=True,
    )
    required = {"atr", "vp_vah", "vp_val", "acceptance_into_value"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=False,
    )

    assert result.valid is False
    assert "atr" in result.non_finite_columns


# ---------------------------------------------------------------------------
# None values
# ---------------------------------------------------------------------------

def test_none_in_required_column_rejects() -> None:
    validator = EnrichmentValidator()
    bar = _bar(
        close=50500.0,
        atr=None,
        vp_vah=52000.0,
        vp_val=50000.0,
        acceptance_into_value=True,
    )
    required = {"atr", "vp_vah", "vp_val", "acceptance_into_value"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=False,
    )

    assert result.valid is False
    # None in a numeric column is a non-finite column
    assert "atr" in result.non_finite_columns


# ---------------------------------------------------------------------------
# Invalid boolean type
# ---------------------------------------------------------------------------

def test_string_where_boolean_required_rejects() -> None:
    validator = EnrichmentValidator()
    bar = _bar(
        close=50500.0,
        atr=1200.0,
        vp_vah=52000.0,
        vp_val=50000.0,
        acceptance_into_value="yes",
    )
    required = {"atr", "vp_vah", "vp_val", "acceptance_into_value"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=False,
    )

    assert result.valid is False
    assert "acceptance_into_value" in result.invalid_type_columns


# ---------------------------------------------------------------------------
# Warmup / gap gates
# ---------------------------------------------------------------------------

def test_warmup_not_ready_rejects() -> None:
    validator = EnrichmentValidator()
    bar = _bar(close=50500.0, atr=1200.0)
    required = {"atr"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=False,
        has_gap=False,
    )

    assert result.valid is False
    assert "warmup" in result.reason.lower()


def test_gap_detected_rejects() -> None:
    validator = EnrichmentValidator()
    bar = _bar(close=50500.0, atr=1200.0)
    required = {"atr"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=True,
    )

    assert result.valid is False
    assert "gap" in result.reason.lower()


# ---------------------------------------------------------------------------
# Optional columns
# ---------------------------------------------------------------------------

def test_optional_non_required_nan_does_not_block() -> None:
    """Non-required columns with NaN/None do not block evaluation."""
    validator = EnrichmentValidator()
    bar = _bar(
        close=50500.0,
        atr=1200.0,
        vp_vah=52000.0,
        vp_val=50000.0,
        rsi_14=float("nan"),
        optional_field=None,
    )
    required = {"atr", "vp_vah", "vp_val"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=False,
    )

    assert result.valid is True


def test_optional_non_required_missing_does_not_block() -> None:
    """Non-required columns that are missing do not block evaluation."""
    validator = EnrichmentValidator()
    bar = _bar(close=50500.0, atr=1200.0)
    required = {"atr"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=False,
    )

    assert result.valid is True


# ---------------------------------------------------------------------------
# Multiple failures are all reported
# ---------------------------------------------------------------------------

def test_multiple_failures_all_reported() -> None:
    validator = EnrichmentValidator()
    bar = _bar(
        close=50500.0,
        atr=float("nan"),
        acceptance_into_value="yes",
    )
    required = {"atr", "vp_vah", "vp_val", "acceptance_into_value"}

    result = validator.validate(
        enriched_bar=bar,
        required_columns=required,
        warmup_ready=True,
        has_gap=False,
    )

    assert result.valid is False
    assert "atr" in result.non_finite_columns
    assert "vp_vah" in result.missing_columns
    assert "vp_val" in result.missing_columns
    assert "acceptance_into_value" in result.invalid_type_columns
