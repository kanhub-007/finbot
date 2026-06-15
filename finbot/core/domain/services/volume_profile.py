"""Proxy Volume Profile — approximate POC/VAH/VAL from OHLCV bars.

Since finbar has OHLCV data (not tick-level volume-at-price), we
approximate the volume distribution within each bar using Parkinson
volatility as the spread parameter. Volume is modeled as normally
distributed around the bar's typical price, truncated to the bar's
high-low range.

Per-session, volume from all bars is aggregated into price buckets,
and the 68% Value Area with Point of Control is extracted.

All functions are pure — no state, no I/O.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from finbar_strategy_runtime.domain.entities.volume_profile_result import (
    VolumeProfileResult,
)

from finbot.core.domain.services._profile_utils import expand_value_area

# ---------------------------------------------------------------------------
# Per-bar volume distribution
# ---------------------------------------------------------------------------


def _parkinson_sigma(high: float, low: float) -> float:
    """Parkinson (1980) volatility for a single bar: ln(H/L) / (2·√ln2)."""
    if low <= 0 or high <= low:
        return 0.0
    return math.log(high / low) / (2.0 * math.sqrt(math.log(2)))


def _distribute_bar_volume(
    bar_high: float,
    bar_low: float,
    bar_close: float,
    bar_volume: float,
    price_buckets: np.ndarray,
    bucket_size: float,
) -> np.ndarray:
    """Distribute one bar's volume across price buckets.

    Uses a normal distribution centered at typical price with
    Parkinson-derived sigma, truncated to [bar_low, bar_high].

    Args:
        bar_high: Bar high price.
        bar_low: Bar low price.
        bar_close: Bar close price.
        bar_volume: Total volume for this bar.
        price_buckets: Array of bucket center prices.
        bucket_size: Width of each price bucket.

    Returns:
        Array of volume per bucket for this bar.
    """
    tp = (bar_high + bar_low + bar_close) / 3.0
    sigma = _parkinson_sigma(bar_high, bar_low)

    if sigma <= 0 or bar_volume <= 0:
        # Degenerate bar — assign all volume to nearest bucket
        result = np.zeros(len(price_buckets))
        if len(price_buckets) > 0:
            nearest = np.argmin(np.abs(price_buckets - tp))
            result[nearest] = bar_volume
        return result

    # Normal PDF evaluated at each bucket center
    z = (price_buckets - tp) / sigma
    pdf = np.exp(-0.5 * z**2) / (sigma * math.sqrt(2 * math.pi))

    # Truncate to bar's high-low range with soft edges
    half_bucket = bucket_size / 2.0
    below_low = price_buckets + half_bucket < bar_low
    above_high = price_buckets - half_bucket > bar_high

    # Attenuate buckets outside bar's high-low range
    pdf[below_low | above_high] *= 0.1

    total_pdf = pdf.sum()
    if total_pdf <= 0:
        return np.zeros(len(price_buckets))

    return (pdf / total_pdf) * bar_volume


def _distribute_bars_volume_vectorised(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    price_buckets: np.ndarray,
    bucket_size: float,
) -> np.ndarray:
    """Distribute volume across price buckets for ALL bars at once.

    Vectorised equivalent of calling :func:`_distribute_bar_volume` per bar.
    Returns an ``(n_bars, n_buckets)`` array of volume-per-bucket-per-bar.
    Bars with non-positive volume or degenerate range return all-zeros rows.
    """
    n_bars = len(volumes)
    n_buckets = len(price_buckets)
    if n_bars == 0 or n_buckets == 0:
        return np.zeros((n_bars, n_buckets))

    # Typical price and Parkinson sigma per bar (vectorised).
    highs_f = highs.astype(float)
    lows_f = lows.astype(float)
    closes_f = closes.astype(float)
    tp = (highs_f + lows_f + closes_f) / 3.0
    # Parkinson sigma = ln(H/L) / (2·√ln2); 0 for degenerate bars.
    safe_ratio = np.where((lows_f > 0) & (highs_f > lows_f), highs_f / lows_f, 1.0)
    sigma = np.log(safe_ratio) / (2.0 * math.sqrt(math.log(2)))
    sigma = np.where(sigma > 0, sigma, 0.0)

    # Broadcast to (n_bars, n_buckets): z = (bucket - tp) / sigma
    tp_col = tp.reshape(-1, 1)  # (n_bars, 1)
    sigma_col = sigma.reshape(-1, 1)  # (n_bars, 1)
    buckets_row = price_buckets.reshape(1, -1)  # (1, n_buckets)

    valid_sigma = sigma_col > 0
    safe_sigma = np.where(valid_sigma, sigma_col, 1.0)
    z = (buckets_row - tp_col) / safe_sigma
    pdf = np.where(
        valid_sigma,
        np.exp(-0.5 * z**2) / (safe_sigma * math.sqrt(2 * math.pi)),
        0.0,
    )

    # Soft-truncate buckets outside each bar's high-low range (×0.1).
    half_bucket = bucket_size / 2.0
    below_low = (buckets_row + half_bucket) < lows_f.reshape(-1, 1)
    above_high = (buckets_row - half_bucket) > highs_f.reshape(-1, 1)
    pdf = np.where(below_low | above_high, pdf * 0.1, pdf)

    # Degenerate bars (sigma <= 0, i.e. high == low) have no spread.  The
    # per-bar reference returns early — BEFORE truncation — placing ALL volume
    # at the nearest bucket, so do the same here AFTER truncation to override
    # any attenuation applied to the nearest bucket.
    degenerate = (sigma <= 0).reshape(-1)
    if degenerate.any():
        deg_tp = tp[degenerate].reshape(-1, 1)
        nearest = np.argmin(np.abs(price_buckets.reshape(1, -1) - deg_tp), axis=1)
        for row, idx in zip(np.nonzero(degenerate)[0], nearest, strict=True):
            pdf[row, idx] = 1.0

    # Normalise each bar's distribution to sum to 1, then scale by volume.
    totals = pdf.sum(axis=1, keepdims=True)
    totals_safe = np.where(totals > 0, totals, 1.0)
    fractions = np.where(totals > 0, pdf / totals_safe, 0.0)

    vol_col = volumes.astype(float).reshape(-1, 1)
    vol_col = np.where(vol_col > 0, vol_col, 0.0)
    return fractions * vol_col


# ---------------------------------------------------------------------------
# Session Volume Profile
# ---------------------------------------------------------------------------


def compute_session_volume_profile(
    session_bars: pd.DataFrame,
    num_buckets: int = 100,
) -> VolumeProfileResult:
    """Build an approximate Volume Profile from a session's OHLCV bars.

    Aggregates volume from all bars into price buckets, using
    Parkinson-weighted normal distribution within each bar, then
    extracts POC, VAH, and VAL from the resulting profile.

    Args:
        session_bars: DataFrame with columns [high, low, close, volume]
            for a single trading session.
        num_buckets: Number of price buckets (default 100).

    Returns:
        VolumeProfileResult with POC, VAH, VAL, and profile data.
    """
    if session_bars.empty:
        return VolumeProfileResult(
            poc=0.0,
            vah=0.0,
            val=0.0,
            total_volume=0.0,
            value_area_volume=0.0,
            bucket_size=0.0,
            num_buckets=num_buckets,
        )

    session_high = float(session_bars["high"].max())
    session_low = float(session_bars["low"].min())

    if session_high <= session_low:
        return VolumeProfileResult(
            poc=session_high,
            vah=session_high,
            val=session_low,
            total_volume=0.0,
            value_area_volume=0.0,
            bucket_size=0.0,
            num_buckets=num_buckets,
        )

    # Create price buckets spanning the session range with a small buffer
    buffer = (session_high - session_low) * 0.02
    price_min = session_low - buffer
    price_max = session_high + buffer
    bucket_size = (price_max - price_min) / num_buckets
    price_buckets = np.linspace(
        price_min + bucket_size / 2,
        price_max - bucket_size / 2,
        num_buckets,
    )

    # Aggregate volume across all bars (vectorised — replaces iterrows loop).
    volumes = session_bars["volume"].to_numpy(dtype=float)
    total_volume = float(volumes[volumes > 0].sum())
    if total_volume <= 0:
        return VolumeProfileResult(
            poc=float(session_bars["close"].iloc[-1]),
            vah=float(session_bars["high"].max()),
            val=float(session_bars["low"].min()),
            total_volume=0.0,
            value_area_volume=0.0,
            bucket_size=bucket_size,
            num_buckets=num_buckets,
        )

    per_bar = _distribute_bars_volume_vectorised(
        session_bars["high"].to_numpy(),
        session_bars["low"].to_numpy(),
        session_bars["close"].to_numpy(),
        volumes,
        price_buckets,
        bucket_size,
    )
    volume_profile = per_bar.sum(axis=0)

    # POC: price bucket with maximum volume
    poc_idx = int(np.argmax(volume_profile))
    poc = float(price_buckets[poc_idx])

    # Value Area: expand outward from POC until 68% of volume captured
    lower_idx, upper_idx, accumulated = expand_value_area(
        volume_profile, poc_idx, total_volume
    )

    vah = float(price_buckets[upper_idx]) + bucket_size / 2
    val = float(price_buckets[lower_idx]) - bucket_size / 2
    value_area_volume = float(accumulated)

    return VolumeProfileResult(
        poc=poc,
        vah=vah,
        val=val,
        total_volume=total_volume,
        value_area_volume=value_area_volume,
        bucket_size=bucket_size,
        num_buckets=num_buckets,
        profile=None,
    )


# ---------------------------------------------------------------------------
# DataFrame-level computation (per-session)
# ---------------------------------------------------------------------------


def compute_all_session_volume_profiles(
    df: pd.DataFrame,
    num_buckets: int = 100,
) -> pd.DataFrame:
    """Compute Volume Profile POC/VAH/VAL for each session in a DataFrame.

    Groups bars by calendar date, computes a Volume Profile per session,
    and broadcasts POC/VAH/VAL to all bars in that session.

    Args:
        df: DataFrame with columns [high, low, close, volume]
            and a datetime index.
        num_buckets: Number of price buckets per profile.

    Returns:
        DataFrame with added columns: vp_poc, vp_vah, vp_val.
    """
    result = df.copy()
    result["vp_poc"] = np.nan
    result["vp_vah"] = np.nan
    result["vp_val"] = np.nan

    date_series = pd.Series(
        pd.to_datetime(result.index).strftime("%Y-%m-%d"), index=result.index
    )

    for date, idx in date_series.groupby(date_series).groups.items():
        session = df.loc[idx]
        profile = compute_session_volume_profile(session, num_buckets=num_buckets)

        result.loc[idx, "vp_poc"] = profile.poc
        result.loc[idx, "vp_vah"] = profile.vah
        result.loc[idx, "vp_val"] = profile.val

    return result


# ---------------------------------------------------------------------------
# Rolling / Composite Value Areas
# ---------------------------------------------------------------------------


def compute_rolling_vp(
    df: pd.DataFrame,
    window: int = 5,
) -> pd.DataFrame:
    """Compute rolling N-session median of Volume Profile POC/VAH/VAL.

    Groups by session, extracts one value per session, computes
    rolling median over ``window`` sessions, and broadcasts to all
    bars in each session.

    Requires: vp_poc, vp_vah, vp_val columns already on df.

    Args:
        df: DataFrame with vp_poc, vp_vah, vp_val columns.
        window: Number of sessions in rolling window (default 5).

    Returns:
        DataFrame with added columns: vp_poc_{window}d, vp_vah_{window}d,
        vp_val_{window}d.
    """
    result = df.copy()

    poc_col = f"vp_poc_{window}d"
    vah_col = f"vp_vah_{window}d"
    val_col = f"vp_val_{window}d"

    result[poc_col] = np.nan
    result[vah_col] = np.nan
    result[val_col] = np.nan

    if "vp_poc" not in df.columns:
        return result

    date_series = pd.Series(
        pd.to_datetime(result.index).strftime("%Y-%m-%d"),
        index=result.index,
    )

    # Extract one value per session (all bars in a session share the same VP)
    session_poc: dict[str, float] = {}
    session_vah: dict[str, float] = {}
    session_val: dict[str, float] = {}

    for date, idx in date_series.groupby(date_series).groups.items():
        session_poc[date] = float(df["vp_poc"].loc[idx].iloc[-1])
        session_vah[date] = float(df["vp_vah"].loc[idx].iloc[-1])
        session_val[date] = float(df["vp_val"].loc[idx].iloc[-1])

    ordered_dates = sorted(session_poc.keys())

    if len(ordered_dates) < window:
        return result

    # Rolling median over sessions — one vectorised pandas call instead of
    # a Python loop calling np.median per session.
    poc_series = pd.Series([session_poc[d] for d in ordered_dates], index=ordered_dates)
    vah_series = pd.Series([session_vah[d] for d in ordered_dates], index=ordered_dates)
    val_series = pd.Series([session_val[d] for d in ordered_dates], index=ordered_dates)
    rolling_poc = poc_series.rolling(window=window).median()
    rolling_vah = vah_series.rolling(window=window).median()
    rolling_val = val_series.rolling(window=window).median()

    for i in range(window - 1, len(ordered_dates)):
        current_date = ordered_dates[i]
        idx = date_series[date_series == current_date].index
        result.loc[idx, poc_col] = rolling_poc.iloc[i]
        result.loc[idx, vah_col] = rolling_vah.iloc[i]
        result.loc[idx, val_col] = rolling_val.iloc[i]

    return result


# ---------------------------------------------------------------------------
# Rolling-window Volume Profile — bar-based windows (24/7 crypto markets)
# ---------------------------------------------------------------------------


def compute_rolling_window_vp(
    df: pd.DataFrame,
    window_bars: int = 48,
    num_buckets: int = 100,
) -> pd.DataFrame:
    """Compute Volume Profile over a trailing bar window.

    Unlike session-based VP (which groups by calendar date), this uses
    a rolling N-bar window. Each bar gets POC/VAH/VAL computed from the
    trailing ``window_bars`` bars. Works for any market — crypto (24/7),
    equities (with after-hours), forex.

    Args:
        df: DataFrame with columns [high, low, close, volume]
            and a datetime index.
        window_bars: Number of bars in the trailing window (default 48 =
            24 hours at 30min).
        num_buckets: Number of price buckets per profile.

    Returns:
        DataFrame with added columns: rvp_poc_{window_bars},
        rvp_vah_{window_bars}, rvp_val_{window_bars}.
    """
    result = df.copy()

    poc_col = f"rvp_poc_{window_bars}"
    vah_col = f"rvp_vah_{window_bars}"
    val_col = f"rvp_val_{window_bars}"

    result[poc_col] = np.nan
    result[vah_col] = np.nan
    result[val_col] = np.nan

    if len(result) < window_bars:
        return result

    # Compute each window's profile (already vectorised internally) and
    # collect into arrays, then bulk-assign once — avoids slow per-row
    # result.iloc[i, ...] = scalar writes.
    n = len(result)
    poc_arr = np.full(n, np.nan)
    vah_arr = np.full(n, np.nan)
    val_arr = np.full(n, np.nan)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    volume = df["volume"].to_numpy(dtype=float)
    for i in range(window_bars - 1, n):
        s = slice(i - window_bars + 1, i + 1)
        window = pd.DataFrame(
            {"high": high[s], "low": low[s], "close": close[s], "volume": volume[s]},
            index=df.index[s],
        )
        profile = compute_session_volume_profile(window, num_buckets=num_buckets)
        poc_arr[i] = profile.poc
        vah_arr[i] = profile.vah
        val_arr[i] = profile.val

    result[poc_col] = poc_arr
    result[vah_col] = vah_arr
    result[val_col] = val_arr
    return result
