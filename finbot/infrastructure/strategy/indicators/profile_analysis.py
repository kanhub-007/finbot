"""Profile-shape, Wyckoff, and coil classifiers.

These indicators share computation (Wyckoff phases depend on profile shape;
boolean wrappers depend on the phase classification) so they live together.
Each handler self-registers via ``@register(name)`` on import.
"""

from __future__ import annotations

from finbot.infrastructure.strategy.indicator_registry import register
from finbot.infrastructure.strategy.indicators._shared import (
    classify_all_profile_shapes,
    classify_wyckoff_phase,
    compute_is_accumulation,
    compute_is_b_shape,
    compute_is_d_shape,
    compute_is_distribution,
    compute_is_markdown,
    compute_is_markup,
    compute_is_neutral_shape,
    compute_is_normal_shape,
    compute_is_p_shape,
    compute_is_wyckoff_neutral,
    detect_coil,
)

# ---------------------------------------------------------------------------
# Profile Shape Classifier
# ---------------------------------------------------------------------------


@register("profile_shape")
def _profile_shape(df, _name, cache):
    if "__profile_shape_done" in cache:
        return df
    result = classify_all_profile_shapes(df)
    cache["__profile_shape_done"] = True
    if "profile_shape" in result.columns:
        df["profile_shape"] = result["profile_shape"]
    return df


# ---------------------------------------------------------------------------
# Coil / Squeeze Detector
# ---------------------------------------------------------------------------


@register("is_coiled")
def _is_coiled(df, _name, cache):
    return _compute_coil(df, cache)


@register("coil_intensity")
def _coil_intensity(df, _name, cache):
    return _compute_coil(df, cache)


def _compute_coil(df, cache):
    if "__coil_done" in cache:
        return df
    result = detect_coil(df)
    cache["__coil_done"] = True
    for col in ("is_coiled", "coil_intensity"):
        if col in result.columns:
            df[col] = result[col]
    return df


# ---------------------------------------------------------------------------
# Wyckoff Phase Classifier
# ---------------------------------------------------------------------------


@register("wyckoff_phase", requires={"profile_shape"})
def _wyckoff_phase(df, _name, cache):
    return _compute_wyckoff(df, cache)


@register("poc_slope_5", requires={"vp_poc"})
def _poc_slope_5(df, _name, cache):
    return _compute_wyckoff(df, cache)


@register("poc_slope_20", requires={"vp_poc"})
def _poc_slope_20(df, _name, cache):
    return _compute_wyckoff(df, cache)


def _compute_wyckoff(df, cache):
    if "__wyckoff_done" in cache:
        return df
    if "__profile_shape_done" not in cache and "profile_shape" not in df.columns:
        df = _profile_shape(df, "profile_shape", cache)
    result = classify_wyckoff_phase(df)
    cache["__wyckoff_done"] = True
    for col in ("wyckoff_phase", "poc_slope_5", "poc_slope_20"):
        if col in result.columns:
            df[col] = result[col]
    return df


# ---------------------------------------------------------------------------
# Wyckoff Phase Boolean Wrappers
# ---------------------------------------------------------------------------


@register("is_accumulation")
def _is_accumulation(df, _name, cache):
    return _compute_wyckoff_wrappers(df, cache)


@register("is_markup")
def _is_markup(df, _name, cache):
    return _compute_wyckoff_wrappers(df, cache)


@register("is_distribution")
def _is_distribution(df, _name, cache):
    return _compute_wyckoff_wrappers(df, cache)


@register("is_markdown")
def _is_markdown(df, _name, cache):
    return _compute_wyckoff_wrappers(df, cache)


@register("is_wyckoff_neutral")
def _is_wyckoff_neutral(df, _name, cache):
    return _compute_wyckoff_wrappers(df, cache)


def _compute_wyckoff_wrappers(df, cache):
    if "__wyckoff_wrappers_done" in cache:
        return df
    if "__wyckoff_done" not in cache and "wyckoff_phase" not in df.columns:
        df = _wyckoff_phase(df, "wyckoff_phase", cache)
    result = compute_is_accumulation(df)
    result = compute_is_markup(result)
    result = compute_is_distribution(result)
    result = compute_is_markdown(result)
    result = compute_is_wyckoff_neutral(result)
    cache["__wyckoff_wrappers_done"] = True
    for col in (
        "is_accumulation",
        "is_markup",
        "is_distribution",
        "is_markdown",
        "is_wyckoff_neutral",
    ):
        if col in result.columns:
            df[col] = result[col]
    return df


# ---------------------------------------------------------------------------
# Profile Shape Boolean Wrappers
# ---------------------------------------------------------------------------


@register("is_normal_shape")
def _is_normal_shape(df, _name, cache):
    return _compute_shape_wrappers(df, cache)


@register("is_b_shape")
def _is_b_shape(df, _name, cache):
    return _compute_shape_wrappers(df, cache)


@register("is_p_shape")
def _is_p_shape(df, _name, cache):
    return _compute_shape_wrappers(df, cache)


@register("is_d_shape")
def _is_d_shape(df, _name, cache):
    return _compute_shape_wrappers(df, cache)


@register("is_neutral_shape")
def _is_neutral_shape(df, _name, cache):
    return _compute_shape_wrappers(df, cache)


def _compute_shape_wrappers(df, cache):
    if "__shape_wrappers_done" in cache:
        return df
    if "__profile_shape_done" not in cache and "profile_shape" not in df.columns:
        df = _profile_shape(df, "profile_shape", cache)
    result = compute_is_normal_shape(df)
    result = compute_is_b_shape(result)
    result = compute_is_p_shape(result)
    result = compute_is_d_shape(result)
    result = compute_is_neutral_shape(result)
    cache["__shape_wrappers_done"] = True
    for col in (
        "is_normal_shape",
        "is_b_shape",
        "is_p_shape",
        "is_d_shape",
        "is_neutral_shape",
    ):
        if col in result.columns:
            df[col] = result[col]
    return df
