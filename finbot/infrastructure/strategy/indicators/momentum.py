"""Momentum / moving-average indicators — RSI, SMA, EMA, MACD, and auxiliaries.

Each handler self-registers via ``@register(name)`` on import.
"""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta

from finbot.infrastructure.strategy.indicator_registry import register, safe_ta


@register("rsi_7")
def _rsi_7(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["rsi_7"] = safe_ta(ta.rsi, df["close"], length=7)
    return df


@register("rsi_14")
def _rsi_14(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["rsi_14"] = safe_ta(ta.rsi, df["close"], length=14)
    return df


@register("sma_10")
def _sma_10(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["sma_10"] = safe_ta(ta.sma, df["close"], length=10)
    return df


@register("sma_20")
def _sma_20(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["sma_20"] = safe_ta(ta.sma, df["close"], length=20)
    return df


@register("sma_30")
def _sma_30(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["sma_30"] = safe_ta(ta.sma, df["close"], length=30)
    return df


@register("sma_50")
def _sma_50(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["sma_50"] = safe_ta(ta.sma, df["close"], length=50)
    return df


@register("sma_200")
def _sma_200(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["sma_200"] = safe_ta(ta.sma, df["close"], length=200)
    return df


@register("ema_12")
def _ema_12(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["ema_12"] = safe_ta(ta.ema, df["close"], length=12)
    return df


@register("ema_26")
def _ema_26(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["ema_26"] = safe_ta(ta.ema, df["close"], length=26)
    return df


@register("macd")
def _macd(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    """Compute MACD, signal line, and histogram in one call.

    Caches the result so subsequent requests for macd_signal / macd_hist
    don't recompute.
    """
    if "macd" in cache:
        macd_df = cache["macd"]
    else:
        macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd_df is None:
            return df
        cache["macd"] = macd_df
    df["macd"] = macd_df.get("MACD_12_26_9")
    return df


@register("macd_signal")
def _macd_signal(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    if "macd" not in cache:
        macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd_df is None:
            return df
        cache["macd"] = macd_df
    df["macd_signal"] = cache["macd"].get("MACDs_12_26_9")
    return df


@register("macd_hist")
def _macd_hist(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    if "macd" not in cache:
        macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd_df is None:
            return df
        cache["macd"] = macd_df
    df["macd_hist"] = cache["macd"].get("MACDh_12_26_9")
    return df


@register("ibs")
def _ibs(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    price_range = df["high"] - df["low"]
    df["ibs"] = (df["close"] - df["low"]) / price_range.replace(0, pd.NA)
    return df


@register("rvol")
def _rvol(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    vol_sma = safe_ta(ta.sma, df["volume"], length=20)
    if vol_sma is not None:
        df["rvol"] = df["volume"] / vol_sma.replace(0, pd.NA)
    return df


@register("ker")
def _ker(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["ker"] = safe_ta(ta.er, df["close"], length=10)
    return df


@register("kama")
def _kama(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["kama"] = safe_ta(ta.kama, df["close"], length=10)
    return df


@register("price_vs_sma20", requires={"sma_20"})
def _price_vs_sma20(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["price_vs_sma20"] = "AT"
    mask = df["sma_20"].notna()
    df.loc[mask & (df["close"] > df["sma_20"]), "price_vs_sma20"] = "ABOVE"
    df.loc[mask & (df["close"] < df["sma_20"]), "price_vs_sma20"] = "BELOW"
    return df
