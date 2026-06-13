"""Volatility indicators — ATR, ADX, volatility buffers, and proxy ATR.

Each handler self-registers via ``@register(name)`` on import.
"""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta

from finbot.infrastructure.strategy.indicator_registry import register, safe_ta


@register("atr")
def _atr(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["atr"] = safe_ta(ta.atr, df["high"], df["low"], df["close"], length=14)
    return df


@register("adx")
def _adx(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
    if adx_df is not None and "ADX_14" in adx_df.columns:
        df["adx"] = adx_df["ADX_14"]
    return df


@register("vol_buffer_high", requires={"atr"})
def _vol_buffer_high(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["vol_buffer_high"] = df["open"] + (df["atr"] * 0.1)
    return df


@register("vol_buffer_low", requires={"atr"})
def _vol_buffer_low(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["vol_buffer_low"] = df["open"] - (df["atr"] * 0.1)
    return df


@register("proxy_atr")
def _proxy_atr(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    """Wilder RMA ATR from high/low/close."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1).fillna(close)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    df["proxy_atr"] = atr
    return df
