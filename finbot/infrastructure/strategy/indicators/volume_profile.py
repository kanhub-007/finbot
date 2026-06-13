"""Volume Profile indicators — session, rolling, rolling-window, and composite.

Also owns the parameterized rolling-VP dynamic dispatcher used by the
calculator for names like ``vp_poc_10d`` / ``rvp_poc_48`` / ``cvp_poc_10d``.

Each handler self-registers via ``@register(name)`` on import.
"""

from __future__ import annotations

import pandas as pd

from finbot.core.domain.services.volume_profile import (
    compute_all_session_volume_profiles,
    compute_rolling_vp,
    compute_rolling_window_vp,
)
from finbot.infrastructure.strategy.indicator_registry import register
from finbot.infrastructure.strategy.indicators._shared import compute_composite_vp

# ---------------------------------------------------------------------------
# Proxy Volume Profile — POC/VAH/VAL (Auction Market Theory)
# ---------------------------------------------------------------------------

_VP_CACHE_KEY = "__volume_profile_done"


@register("vp_poc")
def _vp_poc(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_volume_profile(df, cache)


@register("vp_vah")
def _vp_vah(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_volume_profile(df, cache)


@register("vp_val")
def _vp_val(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_volume_profile(df, cache)


def _compute_volume_profile(df: pd.DataFrame, cache: dict) -> pd.DataFrame:
    """Compute session Volume Profile (POC/VAH/VAL), cached across calls."""
    if _VP_CACHE_KEY in cache:
        return df
    result = compute_all_session_volume_profiles(df)
    cache[_VP_CACHE_KEY] = True
    for col in ("vp_poc", "vp_vah", "vp_val"):
        if col in result.columns:
            df[col] = result[col]
    return df


# ---------------------------------------------------------------------------
# Rolling / Composite Volume Profile
# ---------------------------------------------------------------------------

_ROLLING_VP_CACHE_KEY = "__rolling_vp_done"


@register("vp_poc_5d", requires={"vp_poc", "vp_vah", "vp_val"})
def _vp_poc_5d(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_vp(df, cache, 5)
    return df


@register("vp_vah_5d", requires={"vp_poc", "vp_vah", "vp_val"})
def _vp_vah_5d(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_vp(df, cache, 5)
    return df


@register("vp_val_5d", requires={"vp_poc", "vp_vah", "vp_val"})
def _vp_val_5d(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_vp(df, cache, 5)
    return df


@register("vp_poc_20d", requires={"vp_poc", "vp_vah", "vp_val"})
def _vp_poc_20d(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_vp(df, cache, 20)
    return df


@register("vp_vah_20d", requires={"vp_poc", "vp_vah", "vp_val"})
def _vp_vah_20d(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_vp(df, cache, 20)
    return df


@register("vp_val_20d", requires={"vp_poc", "vp_vah", "vp_val"})
def _vp_val_20d(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_vp(df, cache, 20)
    return df


def _compute_rolling_vp(df: pd.DataFrame, cache: dict, window: int) -> pd.DataFrame:
    """Compute rolling VP composites for a specific window (cached)."""
    cache_key = f"{_ROLLING_VP_CACHE_KEY}_{window}"
    if cache_key in cache:
        return df
    result = compute_rolling_vp(df, window=window)
    cache[cache_key] = True
    for col in (f"vp_poc_{window}d", f"vp_vah_{window}d", f"vp_val_{window}d"):
        if col in result.columns:
            df[col] = result[col]
    return df


# ---------------------------------------------------------------------------
# Rolling-window Volume Profile — bar-based windows (crypto / 24-7 markets)
# ---------------------------------------------------------------------------

_RVP_CACHE_KEY = "__rolling_window_vp_done"


@register("rvp_poc_48")
def _rvp_poc_48(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 48)
    return df


@register("rvp_vah_48")
def _rvp_vah_48(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 48)
    return df


@register("rvp_val_48")
def _rvp_val_48(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 48)
    return df


@register("rvp_poc_96")
def _rvp_poc_96(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 96)
    return df


@register("rvp_vah_96")
def _rvp_vah_96(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 96)
    return df


@register("rvp_val_96")
def _rvp_val_96(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 96)
    return df


@register("rvp_poc_336")
def _rvp_poc_336(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 336)
    return df


@register("rvp_vah_336")
def _rvp_vah_336(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 336)
    return df


@register("rvp_val_336")
def _rvp_val_336(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 336)
    return df


def _compute_rolling_window_vp(
    df: pd.DataFrame, cache: dict, window_bars: int
) -> pd.DataFrame:
    """Compute rolling-window VP for a specific bar count (cached)."""
    cache_key = f"{_RVP_CACHE_KEY}_{window_bars}"
    if cache_key in cache:
        return df
    result = compute_rolling_window_vp(df, window_bars=window_bars)
    cache[cache_key] = True
    for col in (
        f"rvp_poc_{window_bars}",
        f"rvp_vah_{window_bars}",
        f"rvp_val_{window_bars}",
    ):
        if col in result.columns:
            df[col] = result[col]
    return df


# ---------------------------------------------------------------------------
# Composite Volume Profile
# ---------------------------------------------------------------------------

_CVP_CACHE_KEY = "__composite_vp_done"


@register("cvp_poc_5d")
def _cvp_poc_5d(df, _name, cache):
    _compute_composite_vp(df, cache, 5)
    return df


@register("cvp_vah_5d")
def _cvp_vah_5d(df, _name, cache):
    _compute_composite_vp(df, cache, 5)
    return df


@register("cvp_val_5d")
def _cvp_val_5d(df, _name, cache):
    _compute_composite_vp(df, cache, 5)
    return df


@register("cvp_poc_10d")
def _cvp_poc_10d(df, _name, cache):
    _compute_composite_vp(df, cache, 10)
    return df


@register("cvp_vah_10d")
def _cvp_vah_10d(df, _name, cache):
    _compute_composite_vp(df, cache, 10)
    return df


@register("cvp_val_10d")
def _cvp_val_10d(df, _name, cache):
    _compute_composite_vp(df, cache, 10)
    return df


@register("cvp_poc_20d")
def _cvp_poc_20d(df, _name, cache):
    _compute_composite_vp(df, cache, 20)
    return df


@register("cvp_vah_20d")
def _cvp_vah_20d(df, _name, cache):
    _compute_composite_vp(df, cache, 20)
    return df


@register("cvp_val_20d")
def _cvp_val_20d(df, _name, cache):
    _compute_composite_vp(df, cache, 20)
    return df


def _compute_composite_vp(df, cache, window):
    cache_key = f"{_CVP_CACHE_KEY}_{window}"
    if cache_key in cache:
        return df
    result = compute_composite_vp(df, window=window)
    cache[cache_key] = True
    for col in (f"cvp_poc_{window}d", f"cvp_vah_{window}d", f"cvp_val_{window}d"):
        if col in result.columns:
            df[col] = result[col]
    return df


# ---------------------------------------------------------------------------
# Parameterized Rolling Volume Profile — vp_poc_Nd, vp_vah_Nd, vp_val_Nd
# ---------------------------------------------------------------------------

# Parameterized rolling VP prefixes for dynamic resolution
_ROLLING_VP_PREFIXES = {"vp_poc_", "vp_vah_", "vp_val_"}
# Rolling-window VP prefixes (bar-based, for crypto/24-7 markets)
_RVP_PREFIXES = {"rvp_poc_", "rvp_vah_", "rvp_val_"}
_CVP_PREFIXES = {"cvp_poc_", "cvp_vah_", "cvp_val_"}


def is_rolling_vp(name: str) -> bool:
    """Return True when name matches rvp_poc_N, rvp_vah_N, or rvp_val_N.

    Accepts any positive integer N >= 1 (e.g. rvp_poc_48, rvp_vah_100).
    Also handles session-based vp_poc_Nd, vp_vah_Nd, vp_val_Nd.
    """
    all_prefixes = _ROLLING_VP_PREFIXES | _RVP_PREFIXES | _CVP_PREFIXES
    for prefix in all_prefixes:
        # Bar-based: rvp_poc_48
        if prefix in _RVP_PREFIXES and name.startswith(prefix):
            inner = name[len(prefix) :]
            if inner.isdigit() and int(inner) >= 1:
                return True
        # Session-based / composite: vp_poc_10d, cvp_poc_10d
        if (
            prefix in (_ROLLING_VP_PREFIXES | _CVP_PREFIXES)
            and name.startswith(prefix)
            and name.endswith("d")
        ):
            inner = name[len(prefix) : -1]
            if inner.isdigit() and int(inner) >= 1:
                return True
    return False


def compute_rolling_vp_dynamic(
    df: pd.DataFrame, name: str, cache: dict
) -> pd.DataFrame:
    """Compute a parameterized rolling VP or RVP indicator.

    Parses the window from the indicator name:
    - rvp_poc_48 → rolling-window VP with 48 bars
    - vp_poc_10d → session-based rolling VP with 10 sessions
    """
    # Rolling-window VP (bar-based, crypto)
    for prefix in _RVP_PREFIXES:
        if name.startswith(prefix):
            inner = name[len(prefix) :]
            if inner.isdigit():
                window_bars = int(inner)
                return _compute_rolling_window_vp(df, cache, window_bars)

    # Composite VP (true stacked, cvp_poc_10d)
    for prefix in _CVP_PREFIXES:
        if name.startswith(prefix) and name.endswith("d"):
            inner = name[len(prefix) : -1]
            if inner.isdigit():
                window = int(inner)
                return _compute_composite_vp(df, cache, window)

    # Session-based rolling VP (vp_poc_10d)
    for prefix in _ROLLING_VP_PREFIXES:
        if name.startswith(prefix) and name.endswith("d"):
            inner = name[len(prefix) : -1]
            window = int(inner)
            if "vp_poc" not in df.columns or "vp_vah" not in df.columns:
                return df
            return _compute_rolling_vp(df, cache, window)

    return df
