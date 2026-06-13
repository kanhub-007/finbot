"""Support / resistance and breakout indicators.

Each handler self-registers via ``@register(name)`` on import.
"""

from __future__ import annotations

import pandas as pd

from finbot.infrastructure.strategy.indicator_registry import register


@register("swing_high_20")
def _swing_high_20(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["swing_high_20"] = df["high"].rolling(window=20, min_periods=5).max()
    return df


@register("swing_low_20")
def _swing_low_20(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["swing_low_20"] = df["low"].rolling(window=20, min_periods=5).min()
    return df


@register("breakout_level", requires={"swing_high_20"})
def _breakout_level(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    if "bb_upper" in df.columns and df["bb_upper"].notna().any():
        df["breakout_level"] = df["bb_upper"].fillna(df["swing_high_20"])
        df["breakout_level_type"] = "BB_UPPER"
    else:
        df["breakout_level"] = df["swing_high_20"]
        df["breakout_level_type"] = "SWING_HIGH"
    return df


@register("breakout_signal", requires={"breakout_level", "swing_low_20"})
def _breakout_signal(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["breakout_signal"] = "NONE"
    df.loc[df["close"] > df["breakout_level"], "breakout_signal"] = "BREAKOUT_UP"
    df.loc[df["close"] < df["swing_low_20"], "breakout_signal"] = "BREAKOUT_DOWN"
    return df


@register("is_power_zone", requires={"swing_high_20"})
def _is_power_zone(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    if "bb_upper" in df.columns:
        safe_swing = df["swing_high_20"].replace(0, pd.NA)
        diff = (df["swing_high_20"] - df["bb_upper"]).abs() / safe_swing
        df["is_power_zone"] = (diff <= 0.005).fillna(False)
    else:
        df["is_power_zone"] = False
    return df


@register("breakout_quality", requires={"rvol", "ibs", "breakout_signal"})
def _breakout_quality(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["breakout_quality"] = "LOW"
    high_q = (
        (df["rvol"] > 1.5)
        & (df["ibs"] > 0.7)
        & (df["breakout_signal"] == "BREAKOUT_UP")
    )
    medium_q = (
        (df["rvol"] > 1.0)
        & (df["ibs"] > 0.5)
        & (df["breakout_signal"] == "BREAKOUT_UP")
    )
    df.loc[medium_q, "breakout_quality"] = "MEDIUM"
    df.loc[high_q, "breakout_quality"] = "HIGH"
    return df
