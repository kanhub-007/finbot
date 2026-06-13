"""Market Profile — TPO-based POC/VAH/VAL (Auction Market Theory).

Each handler self-registers via ``@register(name)`` on import.
"""

from __future__ import annotations

import pandas as pd

from finbot.infrastructure.strategy.indicator_registry import register
from finbot.infrastructure.strategy.indicators._shared import (
    compute_all_session_market_profiles,
)

_MP_CACHE_KEY = "__market_profile_done"


@register("mp_poc")
def _mp_poc(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_market_profile(df, cache)


@register("mp_vah")
def _mp_vah(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_market_profile(df, cache)


@register("mp_val")
def _mp_val(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_market_profile(df, cache)


def _compute_market_profile(df: pd.DataFrame, cache: dict) -> pd.DataFrame:
    """Compute session Market Profile (TPO-based POC/VAH/VAL), cached."""
    if _MP_CACHE_KEY in cache:
        return df
    result = compute_all_session_market_profiles(df)
    cache[_MP_CACHE_KEY] = True
    for col in ("mp_poc", "mp_vah", "mp_val"):
        if col in result.columns:
            df[col] = result[col]
    return df
