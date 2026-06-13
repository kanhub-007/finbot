"""Bands and VWAP indicators — Bollinger Bands, VWAP, proxy VWAP, SD bands.

Each handler self-registers via ``@register(name)`` on import.
"""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta

from finbot.infrastructure.strategy.indicator_registry import register, safe_ta
from finbot.infrastructure.strategy.indicators._shared import (
    compute_vwap_session_bands,
)


@register("vwap")
def _vwap(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["vwap"] = safe_ta(ta.vwap, df["high"], df["low"], df["close"], df["volume"])
    return df


@register("bb_upper", requires={"close"})
def _bb_upper(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    if "bb" not in cache:
        cache["bb"] = ta.bbands(df["close"], length=20, std=2)
        if cache["bb"] is None:
            cache["bb"] = pd.DataFrame()
    bb = cache["bb"]
    if not bb.empty:
        bb_cols = [c for c in bb.columns if c.startswith("BBU_")]
        if bb_cols:
            df["bb_upper"] = bb[bb_cols[0]]
    return df


@register("bb_middle", requires={"close"})
def _bb_middle(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    if "bb" not in cache:
        cache["bb"] = ta.bbands(df["close"], length=20, std=2)
        if cache["bb"] is None:
            cache["bb"] = pd.DataFrame()
    bb = cache["bb"]
    if not bb.empty:
        bb_cols = [c for c in bb.columns if c.startswith("BBM_")]
        if bb_cols:
            df["bb_middle"] = bb[bb_cols[0]]
    return df


@register("bb_lower", requires={"close"})
def _bb_lower(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    if "bb" not in cache:
        cache["bb"] = ta.bbands(df["close"], length=20, std=2)
        if cache["bb"] is None:
            cache["bb"] = pd.DataFrame()
    bb = cache["bb"]
    if not bb.empty:
        bb_cols = [c for c in bb.columns if c.startswith("BBL_")]
        if bb_cols:
            df["bb_lower"] = bb[bb_cols[0]]
    return df


@register("proxy_vwap")
def _proxy_vwap(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    """Typical price as VWAP proxy."""
    df["proxy_vwap"] = (df["high"] + df["low"] + df["close"]) / 3.0
    return df


# ---------------------------------------------------------------------------
# VWAP Standard Deviation Bands — session-scoped (Auction Market Theory)
# ---------------------------------------------------------------------------

_VWAP_BANDS_CACHE_KEY = "__vwap_bands_done"


@register("vwap_upper_1")
def _vwap_upper_1(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_vwap_bands(df, cache)


@register("vwap_lower_1")
def _vwap_lower_1(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_vwap_bands(df, cache)


@register("vwap_upper_2")
def _vwap_upper_2(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_vwap_bands(df, cache)


@register("vwap_lower_2")
def _vwap_lower_2(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_vwap_bands(df, cache)


def _compute_vwap_bands(df: pd.DataFrame, cache: dict) -> pd.DataFrame:
    """Compute session-scoped VWAP and its SD bands (cached across calls)."""
    if _VWAP_BANDS_CACHE_KEY in cache:
        return df
    result = compute_vwap_session_bands(df)
    cache[_VWAP_BANDS_CACHE_KEY] = True
    # Copy columns back to original df
    for col in (
        "vwap_session",
        "vwap_upper_1",
        "vwap_lower_1",
        "vwap_upper_2",
        "vwap_lower_2",
    ):
        if col in result.columns:
            df[col] = result[col]
    return df
