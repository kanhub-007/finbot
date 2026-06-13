"""Auction State classifiers (Auction Market Theory).

These classifiers are computed together by the domain
``classify_auction_state`` service and cached so multiple indicator requests
in one ``calculate()`` call share a single computation.
Each handler self-registers via ``@register(name)`` on import.
"""

from __future__ import annotations

import pandas as pd

from finbot.core.domain.services.auction_state import classify_auction_state
from finbot.infrastructure.strategy.indicator_registry import register

_AUCTION_STATE_CACHE_KEY = "__auction_state_done"


@register("inside_value", requires={"vp_vah", "vp_val"})
def _inside_value(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@register("above_value", requires={"vp_vah"})
def _above_value(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@register("below_value", requires={"vp_val"})
def _below_value(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@register("at_poc", requires={"vp_poc", "vp_vah", "vp_val"})
def _at_poc(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@register("near_vah", requires={"vp_vah", "vp_val"})
def _near_vah(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@register("near_val", requires={"vp_vah", "vp_val"})
def _near_val(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@register("distance_to_vah_pct", requires={"vp_vah"})
def _distance_to_vah_pct(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@register("distance_to_val_pct", requires={"vp_val"})
def _distance_to_val_pct(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@register("value_area_width_pct", requires={"vp_vah", "vp_val"})
def _value_area_width_pct(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@register("balance_status", requires={"vp_vah", "vp_val"})
def _balance_status(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


def _compute_auction_state(df: pd.DataFrame, cache: dict) -> pd.DataFrame:
    """Compute all auction state classifiers (cached across calls)."""
    if _AUCTION_STATE_CACHE_KEY in cache:
        return df
    result = classify_auction_state(df)
    cache[_AUCTION_STATE_CACHE_KEY] = True
    auction_cols = [
        "inside_value",
        "above_value",
        "below_value",
        "at_poc",
        "near_vah",
        "near_val",
        "distance_to_vah_pct",
        "distance_to_val_pct",
        "value_area_width_pct",
        "balance_status",
    ]
    for col in auction_cols:
        if col in result.columns:
            df[col] = result[col]
    return df
