"""AMT Rule Signals (Auction Market Theory).

These composite signals depend on the auction-state classifiers, so they
import ``_compute_auction_state`` from the sibling :mod:`auction` module.
Each handler self-registers via ``@register(name)`` on import.
"""

from __future__ import annotations

import pandas as pd

from finbot.core.domain.services.amt_signals import compute_amt_signals
from finbot.infrastructure.strategy.indicator_registry import register
from finbot.infrastructure.strategy.indicators.auction import (
    _AUCTION_STATE_CACHE_KEY,
    _compute_auction_state,
)

_AMT_SIGNALS_CACHE_KEY = "__amt_signals_done"


@register("acceptance_into_value", requires={"vp_vah", "vp_val"})
def _acceptance_into_value(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_amt_signals(df, cache)


@register("rejection_from_edge", requires={"vp_vah", "vp_val"})
def _rejection_from_edge(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_amt_signals(df, cache)


@register("acceptance_outside_value", requires={"vp_vah", "vp_val"})
def _acceptance_outside_value(
    df: pd.DataFrame, _name: str, cache: dict
) -> pd.DataFrame:
    return _compute_amt_signals(df, cache)


@register("poc_rejection", requires={"vp_poc", "atr"})
def _poc_rejection(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_amt_signals(df, cache)


@register("edge_volume_building", requires={"vp_vah", "vp_val", "rvol"})
def _edge_volume_building(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_amt_signals(df, cache)


@register("value_area_migration", requires={"vp_poc"})
def _value_area_migration(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_amt_signals(df, cache)


def _compute_amt_signals(df: pd.DataFrame, cache: dict) -> pd.DataFrame:
    """Compute all AMT rule signals (cached across calls).

    Ensures auction state columns are computed first as dependencies.
    """
    if _AMT_SIGNALS_CACHE_KEY in cache:
        return df

    # Ensure auction state dependencies are satisfied
    if _AUCTION_STATE_CACHE_KEY not in cache:
        df = _compute_auction_state(df, cache)

    result = compute_amt_signals(df)
    cache[_AMT_SIGNALS_CACHE_KEY] = True

    amt_cols = [
        "acceptance_into_value",
        "rejection_from_edge",
        "acceptance_outside_value",
        "poc_rejection",
        "edge_volume_building",
        "value_area_migration",
    ]
    for col in amt_cols:
        if col in result.columns:
            df[col] = result[col]
    return df
