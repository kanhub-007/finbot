"""Trend indicators — direction, strength, and status classification.

Require SMA and ADX columns to be computed first (declared via ``requires``).
Each handler self-registers via ``@register(name)`` on import.
"""

from __future__ import annotations

import pandas as pd

from finbot.infrastructure.strategy.indicator_registry import register


@register(
    "trend_direction",
    requires={"sma_20", "sma_50", "sma_200"},
)
def _trend_direction(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["trend_direction"] = "NEUTRAL"
    mask = df["sma_200"].notna()
    bull = (
        mask
        & (df["sma_20"] > df["sma_50"])
        & (df["sma_50"] > df["sma_200"])
        & (df["close"] > df["sma_20"])
    )
    bear = (
        mask
        & (df["sma_20"] < df["sma_50"])
        & (df["sma_50"] < df["sma_200"])
        & (df["close"] < df["sma_20"])
    )
    df.loc[bull, "trend_direction"] = "BULLISH"
    df.loc[bear, "trend_direction"] = "BEARISH"
    return df


@register("trend_strength", requires={"adx"})
def _trend_strength(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["trend_strength"] = "MODERATE"
    df.loc[df["adx"] > 25, "trend_strength"] = "STRONG"
    df.loc[df["adx"] < 20, "trend_strength"] = "WEAK"
    return df


@register("trend_status", requires={"adx", "trend_direction"})
def _trend_status(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["trend_status"] = "TRANSITION"
    trending = (df["adx"] > 25) & df["trend_direction"].isin(["BULLISH", "BEARISH"])
    ranging = (df["adx"] < 20) | (df["trend_direction"] == "NEUTRAL")
    df.loc[trending, "trend_status"] = "TRENDING"
    df.loc[ranging, "trend_status"] = "RANGING"
    return df
