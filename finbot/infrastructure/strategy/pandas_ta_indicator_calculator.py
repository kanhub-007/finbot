"""PandasTaIndicatorCalculator — pandas_ta implementation of IndicatorCalculator.

Calculates technical indicators (RSI, SMA, MACD, ATR, etc.) on OHLCV
DataFrames using the pandas_ta library. Also delegates proxy indicators
to the domain proxy_indicator module.

Implements the IndicatorCalculator domain interface via the Strategy pattern.
Uses the Pipeline pattern — the calculate() dispatcher stays under 30 lines,
each indicator group is its own private method.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import pandas as pd
import pandas_ta as ta

from finbot.core.domain.interfaces.indicator_calculator import IndicatorCalculator
from finbot.core.domain.services.amt_signals import (
    compute_amt_signals,
)
from finbot.core.domain.services.auction_state import (
    classify_auction_state,
)
from finbot.core.domain.services.volume_profile import (
    compute_all_session_volume_profiles,
    compute_rolling_vp,
    compute_rolling_window_vp,
)

# --- Lazy imports for non-AMT domain services ---
# These are only needed when a strategy requests indicators beyond the
# AMT target set. They are imported lazily to avoid requiring all 10
# domain service implementations in the MVP.


def _lazy_import(module_name: str, attr: str):
    """Return a callable that imports and delegates on first use."""
    _cached = None

    def _wrapper(*args, **kwargs):
        nonlocal _cached
        if _cached is None:
            import importlib

            mod = importlib.import_module(f"finbot.core.domain.services.{module_name}")
            _cached = getattr(mod, attr)
        return _cached(*args, **kwargs)

    return _wrapper


compute_vwap_session_bands = _lazy_import("vwap_bands", "compute_vwap_session_bands")
classify_wyckoff_phase = _lazy_import("wyckoff_phase", "classify_wyckoff_phase")
compute_is_accumulation = _lazy_import("wyckoff_wrappers", "compute_is_accumulation")
compute_is_markup = _lazy_import("wyckoff_wrappers", "compute_is_markup")
compute_is_distribution = _lazy_import("wyckoff_wrappers", "compute_is_distribution")
compute_is_markdown = _lazy_import("wyckoff_wrappers", "compute_is_markdown")
compute_is_wyckoff_neutral = _lazy_import(
    "wyckoff_wrappers", "compute_is_wyckoff_neutral"
)
compute_composite_vp = _lazy_import("composite_vp", "compute_composite_vp")
classify_all_profile_shapes = _lazy_import(
    "profile_shape", "classify_all_profile_shapes"
)
compute_is_b_shape = _lazy_import("profile_shape_wrappers", "compute_is_b_shape")
compute_is_d_shape = _lazy_import("profile_shape_wrappers", "compute_is_d_shape")
compute_is_neutral_shape = _lazy_import(
    "profile_shape_wrappers", "compute_is_neutral_shape"
)
compute_is_normal_shape = _lazy_import(
    "profile_shape_wrappers", "compute_is_normal_shape"
)
compute_is_p_shape = _lazy_import("profile_shape_wrappers", "compute_is_p_shape")
enrich_dataframe_with_proxies = _lazy_import(
    "proxy_indicator", "enrich_dataframe_with_proxies"
)
compute_all_session_market_profiles = _lazy_import(
    "market_profile", "compute_all_session_market_profiles"
)
detect_coil = _lazy_import("coil_detector", "detect_coil")

logger = logging.getLogger(__name__)

# Minimum bars for meaningful indicator output.
MIN_BARS = 10


# ---------------------------------------------------------------------------
# Safe pandas_ta wrapper
# ---------------------------------------------------------------------------


def _safe_ta(func: Callable, *args, **kwargs) -> pd.Series | None:
    """Call a pandas_ta function and return None-safe result.

    pandas_ta returns None when there are fewer bars than the requested
    period length. This helper converts None to a NaN-filled Series.
    """
    try:
        result = func(*args, **kwargs)
    except Exception:
        result = None
    if result is None:
        series = args[0] if args else kwargs.get("close")
        if series is not None and isinstance(series, pd.Series):
            return pd.Series(float("nan"), index=series.index, dtype="float64")
        return None
    return result


# ---------------------------------------------------------------------------
# Indicator dispatch table
# ---------------------------------------------------------------------------

# Each entry maps an indicator name to a (handler, requires_columns) tuple.
# The dispatcher calls the handler only if all required columns are present.
_INDICATOR_HANDLERS: dict[str, tuple[Callable, set[str]]] = {}


def _register(name: str, requires: set[str] | None = None):
    """Decorator to register an indicator handler."""

    def decorator(func: Callable):
        _INDICATOR_HANDLERS[name] = (func, requires or set())
        return func

    return decorator


# ---------------------------------------------------------------------------
# PandasTaIndicatorCalculator
# ---------------------------------------------------------------------------


class PandasTaIndicatorCalculator(IndicatorCalculator):
    """pandas_ta-backed technical indicator calculator.

    Implements the IndicatorCalculator domain interface. Supports:
    - Real indicators: rsi_7, rsi_14, sma_20, sma_50, sma_200, macd, etc.
    - Proxy indicators: proxy_ibs, proxy_parkinson, proxy_typical_price, etc.
    - Trend indicators: trend_direction, trend_strength, trend_status
    - Support/resistance: swing_high_20, breakout_signal, breakout_quality
    """

    def calculate(self, df: pd.DataFrame, indicators: list[str]) -> pd.DataFrame:
        """Apply requested indicators and return enriched DataFrame.

        Args:
            df: DataFrame with columns [open, high, low, close, volume]
                and a datetime index.
            indicators: List of indicator names to compute.

        Returns:
            DataFrame with original columns plus requested indicator columns.
        """
        if df.empty or not indicators:
            return df.copy()

        result = df.copy()

        if len(result) < MIN_BARS:
            logger.warning(
                "Only %d bars (minimum %d), skipping indicators",
                len(result),
                MIN_BARS,
            )
            return result

        # Cache for compound indicators that share computation
        cache: dict[str, pd.DataFrame] = {}

        for name in indicators:
            if name.startswith("proxy_"):
                result = _compute_proxies(result, cache)
            elif name in _INDICATOR_HANDLERS:
                handler, requires = _INDICATOR_HANDLERS[name]
                if requires and requires - set(result.columns):
                    logger.debug(
                        "Skipping '%s': missing columns %s",
                        name,
                        requires - set(result.columns),
                    )
                    continue
                try:
                    result = handler(result, name, cache)
                except Exception as exc:
                    logger.warning("Failed to compute indicator '%s': %s", name, exc)
            elif _is_dynamic(name):
                try:
                    result = _compute_dynamic(result, name)
                except Exception as exc:
                    logger.warning(
                        "Failed to compute dynamic indicator '%s': %s",
                        name,
                        exc,
                    )
            elif _is_rolling_vp(name):
                try:
                    result = _compute_rolling_vp_dynamic(result, name, cache)
                except Exception as exc:
                    logger.warning(
                        "Failed to compute rolling VP '%s': %s",
                        name,
                        exc,
                    )
            else:
                logger.warning("Unknown indicator: '%s'", name)

        return result


# ---------------------------------------------------------------------------
# Proxy indicators — delegates to domain service
# ---------------------------------------------------------------------------

_PROXY_CACHE_KEY = "__proxies_done"


def _compute_proxies(df: pd.DataFrame, cache: dict) -> pd.DataFrame:
    """Compute all proxy indicators in one batch (delegates to domain module).

    Uses a sentinel key in the per-call cache to avoid recomputing
    across multiple proxy indicator requests in the same calculate() call.
    """
    if _PROXY_CACHE_KEY in cache:
        return df
    result = enrich_dataframe_with_proxies(df)
    cache[_PROXY_CACHE_KEY] = True
    return result


# ---------------------------------------------------------------------------
# Individual indicator handlers (registered via @_register)
# ---------------------------------------------------------------------------


@_register("rsi_7")
def _rsi_7(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["rsi_7"] = _safe_ta(ta.rsi, df["close"], length=7)
    return df


@_register("rsi_14")
def _rsi_14(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["rsi_14"] = _safe_ta(ta.rsi, df["close"], length=14)
    return df


@_register("sma_10")
def _sma_10(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["sma_10"] = _safe_ta(ta.sma, df["close"], length=10)
    return df


@_register("sma_20")
def _sma_20(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["sma_20"] = _safe_ta(ta.sma, df["close"], length=20)
    return df


@_register("sma_30")
def _sma_30(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["sma_30"] = _safe_ta(ta.sma, df["close"], length=30)
    return df


@_register("sma_50")
def _sma_50(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["sma_50"] = _safe_ta(ta.sma, df["close"], length=50)
    return df


@_register("sma_200")
def _sma_200(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["sma_200"] = _safe_ta(ta.sma, df["close"], length=200)
    return df


@_register("ema_12")
def _ema_12(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["ema_12"] = _safe_ta(ta.ema, df["close"], length=12)
    return df


@_register("ema_26")
def _ema_26(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["ema_26"] = _safe_ta(ta.ema, df["close"], length=26)
    return df


@_register("macd")
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


@_register("macd_signal")
def _macd_signal(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    if "macd" not in cache:
        macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd_df is None:
            return df
        cache["macd"] = macd_df
    df["macd_signal"] = cache["macd"].get("MACDs_12_26_9")
    return df


@_register("macd_hist")
def _macd_hist(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    if "macd" not in cache:
        macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd_df is None:
            return df
        cache["macd"] = macd_df
    df["macd_hist"] = cache["macd"].get("MACDh_12_26_9")
    return df


@_register("atr")
def _atr(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["atr"] = _safe_ta(ta.atr, df["high"], df["low"], df["close"], length=14)
    return df


@_register("adx")
def _adx(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
    if adx_df is not None and "ADX_14" in adx_df.columns:
        df["adx"] = adx_df["ADX_14"]
    return df


@_register("vwap")
def _vwap(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["vwap"] = _safe_ta(ta.vwap, df["high"], df["low"], df["close"], df["volume"])
    return df


@_register("bb_upper", requires={"close"})
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


@_register("bb_middle", requires={"close"})
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


@_register("bb_lower", requires={"close"})
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


@_register("ibs")
def _ibs(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    price_range = df["high"] - df["low"]
    df["ibs"] = (df["close"] - df["low"]) / price_range.replace(0, pd.NA)
    return df


@_register("rvol")
def _rvol(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    vol_sma = _safe_ta(ta.sma, df["volume"], length=20)
    if vol_sma is not None:
        df["rvol"] = df["volume"] / vol_sma.replace(0, pd.NA)
    return df


@_register("ker")
def _ker(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["ker"] = _safe_ta(ta.er, df["close"], length=10)
    return df


@_register("kama")
def _kama(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["kama"] = _safe_ta(ta.kama, df["close"], length=10)
    return df


# ---------------------------------------------------------------------------
# Trend indicators (require SMA columns to be computed first)
# ---------------------------------------------------------------------------


@_register("price_vs_sma20", requires={"sma_20"})
def _price_vs_sma20(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["price_vs_sma20"] = "AT"
    mask = df["sma_20"].notna()
    df.loc[mask & (df["close"] > df["sma_20"]), "price_vs_sma20"] = "ABOVE"
    df.loc[mask & (df["close"] < df["sma_20"]), "price_vs_sma20"] = "BELOW"
    return df


@_register(
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


@_register("trend_strength", requires={"adx"})
def _trend_strength(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["trend_strength"] = "MODERATE"
    df.loc[df["adx"] > 25, "trend_strength"] = "STRONG"
    df.loc[df["adx"] < 20, "trend_strength"] = "WEAK"
    return df


@_register("trend_status", requires={"adx", "trend_direction"})
def _trend_status(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["trend_status"] = "TRANSITION"
    trending = (df["adx"] > 25) & df["trend_direction"].isin(["BULLISH", "BEARISH"])
    ranging = (df["adx"] < 20) | (df["trend_direction"] == "NEUTRAL")
    df.loc[trending, "trend_status"] = "TRENDING"
    df.loc[ranging, "trend_status"] = "RANGING"
    return df


# ---------------------------------------------------------------------------
# Support / resistance indicators
# ---------------------------------------------------------------------------


@_register("swing_high_20")
def _swing_high_20(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["swing_high_20"] = df["high"].rolling(window=20, min_periods=5).max()
    return df


@_register("swing_low_20")
def _swing_low_20(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["swing_low_20"] = df["low"].rolling(window=20, min_periods=5).min()
    return df


@_register("breakout_level", requires={"swing_high_20"})
def _breakout_level(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    if "bb_upper" in df.columns and df["bb_upper"].notna().any():
        df["breakout_level"] = df["bb_upper"].fillna(df["swing_high_20"])
        df["breakout_level_type"] = "BB_UPPER"
    else:
        df["breakout_level"] = df["swing_high_20"]
        df["breakout_level_type"] = "SWING_HIGH"
    return df


@_register("breakout_signal", requires={"breakout_level", "swing_low_20"})
def _breakout_signal(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["breakout_signal"] = "NONE"
    df.loc[df["close"] > df["breakout_level"], "breakout_signal"] = "BREAKOUT_UP"
    df.loc[df["close"] < df["swing_low_20"], "breakout_signal"] = "BREAKOUT_DOWN"
    return df


@_register("is_power_zone", requires={"swing_high_20"})
def _is_power_zone(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    if "bb_upper" in df.columns:
        safe_swing = df["swing_high_20"].replace(0, pd.NA)
        diff = (df["swing_high_20"] - df["bb_upper"]).abs() / safe_swing
        df["is_power_zone"] = (diff <= 0.005).fillna(False)
    else:
        df["is_power_zone"] = False
    return df


@_register("breakout_quality", requires={"rvol", "ibs", "breakout_signal"})
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


# ---------------------------------------------------------------------------
# Volatility buffer
# ---------------------------------------------------------------------------


@_register("vol_buffer_high", requires={"atr"})
def _vol_buffer_high(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["vol_buffer_high"] = df["open"] + (df["atr"] * 0.1)
    return df


@_register("vol_buffer_low", requires={"atr"})
def _vol_buffer_low(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    df["vol_buffer_low"] = df["open"] - (df["atr"] * 0.1)
    return df


# ---------------------------------------------------------------------------
# True Initial Balance — grouped by date from intraday bars
# ---------------------------------------------------------------------------

# Bars per initial balance period for common intervals.
# 5min: 12 bars = 1 hour. 15min: 4 bars. 30min: 2 bars. 1h: 1 bar.
_IB_BARS_MAP = {"5min": 12, "15min": 4, "30min": 2, "1h": 1}
_DEFAULT_IB_BARS = 2
_IB_MINUTES_MAP = {"5min": 5, "15min": 15, "30min": 30, "1h": 60}


@_register("ib_high")
def _ib_high(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    _compute_true_ib(df, _get_ib_bars(df))
    return df


@_register("ib_low")
def _ib_low(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    _compute_true_ib(df, _get_ib_bars(df))
    return df


@_register("ib_range")
def _ib_range(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    _compute_true_ib(df, _get_ib_bars(df))
    return df


@_register("ib_midpoint")
def _ib_midpoint(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    _compute_true_ib(df, _get_ib_bars(df))
    return df


def _get_ib_bars(df: pd.DataFrame) -> int:
    """Determine how many bars make up the initial balance period.

    Tries to infer from the index frequency, falls back to 2 bars.
    """
    if len(df) < 2:
        return 1
    delta = df.index[1] - df.index[0]
    minutes = delta.total_seconds() / 60
    for key, bars in _IB_BARS_MAP.items():
        if abs(minutes - _IB_MINUTES_MAP[key]) < 2:
            return bars
    return _DEFAULT_IB_BARS


def _compute_true_ib(df: pd.DataFrame, ib_bars: int) -> None:
    """Compute true Initial Balance levels grouped by date.

    Takes the first ``ib_bars`` bars of each day, computes IB high/low/
    range/midpoint, and broadcasts to all bars in that day.

    Results are cached in the 'ib_cache' sentinel so multiple IB
    indicator requests in the same calculate() call are a no-op.
    """
    if "ib_cache" in df.attrs:
        return
    df.attrs["ib_cache"] = True

    date_series = pd.to_datetime(df.index).strftime("%Y-%m-%d")

    ib_highs: dict[str, float] = {}
    ib_lows: dict[str, float] = {}
    ib_ranges: dict[str, float] = {}
    ib_mids: dict[str, float] = {}

    for date, group in df.groupby(date_series):
        if len(group) >= ib_bars:
            first = group.iloc[:ib_bars]
            h = float(first["high"].max())
            lo = float(first["low"].min())
            ib_highs[date] = h
            ib_lows[date] = lo
            ib_ranges[date] = h - lo
            ib_mids[date] = (h + lo) / 2

    df["ib_high"] = date_series.map(ib_highs)
    df["ib_low"] = date_series.map(ib_lows)
    df["ib_range"] = date_series.map(ib_ranges)
    df["ib_midpoint"] = date_series.map(ib_mids)


@_register("proxy_atr")
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


@_register("proxy_vwap")
def _proxy_vwap(df: pd.DataFrame, _name: str, _cache: dict) -> pd.DataFrame:
    """Typical price as VWAP proxy."""
    df["proxy_vwap"] = (df["high"] + df["low"] + df["close"]) / 3.0
    return df


# ---------------------------------------------------------------------------
# VWAP Standard Deviation Bands — session-scoped (Auction Market Theory)
# ---------------------------------------------------------------------------

_VWAP_BANDS_CACHE_KEY = "__vwap_bands_done"


@_register("vwap_upper_1")
def _vwap_upper_1(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_vwap_bands(df, cache)


@_register("vwap_lower_1")
def _vwap_lower_1(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_vwap_bands(df, cache)


@_register("vwap_upper_2")
def _vwap_upper_2(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_vwap_bands(df, cache)


@_register("vwap_lower_2")
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


# ---------------------------------------------------------------------------
# Proxy Volume Profile — POC/VAH/VAL (Auction Market Theory)
# ---------------------------------------------------------------------------

_VP_CACHE_KEY = "__volume_profile_done"


@_register("vp_poc")
def _vp_poc(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_volume_profile(df, cache)


@_register("vp_vah")
def _vp_vah(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_volume_profile(df, cache)


@_register("vp_val")
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

# Parameterized rolling VP prefixes for dynamic resolution
_ROLLING_VP_PREFIXES = {"vp_poc_", "vp_vah_", "vp_val_"}
# Rolling-window VP prefixes (bar-based, for crypto/24-7 markets)
_RVP_PREFIXES = {"rvp_poc_", "rvp_vah_", "rvp_val_"}
_CVP_PREFIXES = {"cvp_poc_", "cvp_vah_", "cvp_val_"}


@_register("vp_poc_5d", requires={"vp_poc", "vp_vah", "vp_val"})
def _vp_poc_5d(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_vp(df, cache, 5)
    return df


@_register("vp_vah_5d", requires={"vp_poc", "vp_vah", "vp_val"})
def _vp_vah_5d(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_vp(df, cache, 5)
    return df


@_register("vp_val_5d", requires={"vp_poc", "vp_vah", "vp_val"})
def _vp_val_5d(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_vp(df, cache, 5)
    return df


@_register("vp_poc_20d", requires={"vp_poc", "vp_vah", "vp_val"})
def _vp_poc_20d(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_vp(df, cache, 20)
    return df


@_register("vp_vah_20d", requires={"vp_poc", "vp_vah", "vp_val"})
def _vp_vah_20d(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_vp(df, cache, 20)
    return df


@_register("vp_val_20d", requires={"vp_poc", "vp_vah", "vp_val"})
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


@_register("rvp_poc_48")
def _rvp_poc_48(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 48)
    return df


@_register("rvp_vah_48")
def _rvp_vah_48(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 48)
    return df


@_register("rvp_val_48")
def _rvp_val_48(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 48)
    return df


@_register("rvp_poc_96")
def _rvp_poc_96(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 96)
    return df


@_register("rvp_vah_96")
def _rvp_vah_96(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 96)
    return df


@_register("rvp_val_96")
def _rvp_val_96(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 96)
    return df


@_register("rvp_poc_336")
def _rvp_poc_336(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 336)
    return df


@_register("rvp_vah_336")
def _rvp_vah_336(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    _compute_rolling_window_vp(df, cache, 336)
    return df


@_register("rvp_val_336")
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


@_register("cvp_poc_5d")
def _cvp_poc_5d(df, _name, cache):
    _compute_composite_vp(df, cache, 5)
    return df


@_register("cvp_vah_5d")
def _cvp_vah_5d(df, _name, cache):
    _compute_composite_vp(df, cache, 5)
    return df


@_register("cvp_val_5d")
def _cvp_val_5d(df, _name, cache):
    _compute_composite_vp(df, cache, 5)
    return df


@_register("cvp_poc_10d")
def _cvp_poc_10d(df, _name, cache):
    _compute_composite_vp(df, cache, 10)
    return df


@_register("cvp_vah_10d")
def _cvp_vah_10d(df, _name, cache):
    _compute_composite_vp(df, cache, 10)
    return df


@_register("cvp_val_10d")
def _cvp_val_10d(df, _name, cache):
    _compute_composite_vp(df, cache, 10)
    return df


@_register("cvp_poc_20d")
def _cvp_poc_20d(df, _name, cache):
    _compute_composite_vp(df, cache, 20)
    return df


@_register("cvp_vah_20d")
def _cvp_vah_20d(df, _name, cache):
    _compute_composite_vp(df, cache, 20)
    return df


@_register("cvp_val_20d")
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
# Profile Shape Classifier
# ---------------------------------------------------------------------------


@_register("profile_shape")
def _profile_shape(df, _name, cache):
    if "__profile_shape_done" in cache:
        return df
    result = classify_all_profile_shapes(df)
    cache["__profile_shape_done"] = True
    if "profile_shape" in result.columns:
        df["profile_shape"] = result["profile_shape"]
    return df


# ---------------------------------------------------------------------------
# Coil / Squeeze Detector
# ---------------------------------------------------------------------------


@_register("is_coiled")
def _is_coiled(df, _name, cache):
    return _compute_coil(df, cache)


@_register("coil_intensity")
def _coil_intensity(df, _name, cache):
    return _compute_coil(df, cache)


def _compute_coil(df, cache):
    if "__coil_done" in cache:
        return df
    result = detect_coil(df)
    cache["__coil_done"] = True
    for col in ("is_coiled", "coil_intensity"):
        if col in result.columns:
            df[col] = result[col]
    return df


# ---------------------------------------------------------------------------
# Wyckoff Phase Classifier
# ---------------------------------------------------------------------------


@_register("wyckoff_phase", requires={"profile_shape"})
def _wyckoff_phase(df, _name, cache):
    return _compute_wyckoff(df, cache)


@_register("poc_slope_5", requires={"vp_poc"})
def _poc_slope_5(df, _name, cache):
    return _compute_wyckoff(df, cache)


@_register("poc_slope_20", requires={"vp_poc"})
def _poc_slope_20(df, _name, cache):
    return _compute_wyckoff(df, cache)


def _compute_wyckoff(df, cache):
    if "__wyckoff_done" in cache:
        return df
    if "__profile_shape_done" not in cache and "profile_shape" not in df.columns:
        df = _profile_shape(df, "profile_shape", cache)
    result = classify_wyckoff_phase(df)
    cache["__wyckoff_done"] = True
    for col in ("wyckoff_phase", "poc_slope_5", "poc_slope_20"):
        if col in result.columns:
            df[col] = result[col]
    return df


# ---------------------------------------------------------------------------
# Wyckoff Phase Boolean Wrappers
# ---------------------------------------------------------------------------


@_register("is_accumulation")
def _is_accumulation(df, _name, cache):
    return _compute_wyckoff_wrappers(df, cache)


@_register("is_markup")
def _is_markup(df, _name, cache):
    return _compute_wyckoff_wrappers(df, cache)


@_register("is_distribution")
def _is_distribution(df, _name, cache):
    return _compute_wyckoff_wrappers(df, cache)


@_register("is_markdown")
def _is_markdown(df, _name, cache):
    return _compute_wyckoff_wrappers(df, cache)


@_register("is_wyckoff_neutral")
def _is_wyckoff_neutral(df, _name, cache):
    return _compute_wyckoff_wrappers(df, cache)


def _compute_wyckoff_wrappers(df, cache):
    if "__wyckoff_wrappers_done" in cache:
        return df
    if "__wyckoff_done" not in cache and "wyckoff_phase" not in df.columns:
        df = _wyckoff_phase(df, "wyckoff_phase", cache)
    result = compute_is_accumulation(df)
    result = compute_is_markup(result)
    result = compute_is_distribution(result)
    result = compute_is_markdown(result)
    result = compute_is_wyckoff_neutral(result)
    cache["__wyckoff_wrappers_done"] = True
    for col in (
        "is_accumulation",
        "is_markup",
        "is_distribution",
        "is_markdown",
        "is_wyckoff_neutral",
    ):
        if col in result.columns:
            df[col] = result[col]
    return df


# ---------------------------------------------------------------------------
# Profile Shape Boolean Wrappers
# ---------------------------------------------------------------------------


@_register("is_normal_shape")
def _is_normal_shape(df, _name, cache):
    return _compute_shape_wrappers(df, cache)


@_register("is_b_shape")
def _is_b_shape(df, _name, cache):
    return _compute_shape_wrappers(df, cache)


@_register("is_p_shape")
def _is_p_shape(df, _name, cache):
    return _compute_shape_wrappers(df, cache)


@_register("is_d_shape")
def _is_d_shape(df, _name, cache):
    return _compute_shape_wrappers(df, cache)


@_register("is_neutral_shape")
def _is_neutral_shape(df, _name, cache):
    return _compute_shape_wrappers(df, cache)


def _compute_shape_wrappers(df, cache):
    if "__shape_wrappers_done" in cache:
        return df
    if "__profile_shape_done" not in cache and "profile_shape" not in df.columns:
        df = _profile_shape(df, "profile_shape", cache)
    result = compute_is_normal_shape(df)
    result = compute_is_b_shape(result)
    result = compute_is_p_shape(result)
    result = compute_is_d_shape(result)
    result = compute_is_neutral_shape(result)
    cache["__shape_wrappers_done"] = True
    for col in (
        "is_normal_shape",
        "is_b_shape",
        "is_p_shape",
        "is_d_shape",
        "is_neutral_shape",
    ):
        if col in result.columns:
            df[col] = result[col]
    return df


# ---------------------------------------------------------------------------
# Market Profile — TPO-based POC/VAH/VAL (Auction Market Theory)
# ---------------------------------------------------------------------------

_MP_CACHE_KEY = "__market_profile_done"


@_register("mp_poc")
def _mp_poc(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_market_profile(df, cache)


@_register("mp_vah")
def _mp_vah(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_market_profile(df, cache)


@_register("mp_val")
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


# ---------------------------------------------------------------------------
# Auction State Classifiers (Auction Market Theory)
# ---------------------------------------------------------------------------

_AUCTION_STATE_CACHE_KEY = "__auction_state_done"


@_register("inside_value", requires={"vp_vah", "vp_val"})
def _inside_value(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@_register("above_value", requires={"vp_vah"})
def _above_value(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@_register("below_value", requires={"vp_val"})
def _below_value(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@_register("at_poc", requires={"vp_poc", "vp_vah", "vp_val"})
def _at_poc(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@_register("near_vah", requires={"vp_vah", "vp_val"})
def _near_vah(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@_register("near_val", requires={"vp_vah", "vp_val"})
def _near_val(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@_register("distance_to_vah_pct", requires={"vp_vah"})
def _distance_to_vah_pct(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@_register("distance_to_val_pct", requires={"vp_val"})
def _distance_to_val_pct(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@_register("value_area_width_pct", requires={"vp_vah", "vp_val"})
def _value_area_width_pct(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_auction_state(df, cache)


@_register("balance_status", requires={"vp_vah", "vp_val"})
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


# ---------------------------------------------------------------------------
# AMT Rule Signals (Auction Market Theory)
# ---------------------------------------------------------------------------

_AMT_SIGNALS_CACHE_KEY = "__amt_signals_done"


@_register("acceptance_into_value", requires={"vp_vah", "vp_val"})
def _acceptance_into_value(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_amt_signals(df, cache)


@_register("rejection_from_edge", requires={"vp_vah", "vp_val"})
def _rejection_from_edge(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_amt_signals(df, cache)


@_register("acceptance_outside_value", requires={"vp_vah", "vp_val"})
def _acceptance_outside_value(
    df: pd.DataFrame, _name: str, cache: dict
) -> pd.DataFrame:
    return _compute_amt_signals(df, cache)


@_register("poc_rejection", requires={"vp_poc", "atr"})
def _poc_rejection(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_amt_signals(df, cache)


@_register("edge_volume_building", requires={"vp_vah", "vp_val", "rvol"})
def _edge_volume_building(df: pd.DataFrame, _name: str, cache: dict) -> pd.DataFrame:
    return _compute_amt_signals(df, cache)


@_register("value_area_migration", requires={"vp_poc"})
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


# ---------------------------------------------------------------------------
# Dynamic period indicators — handles any period within supported ranges
# ---------------------------------------------------------------------------

_DYNAMIC_HANDLERS: dict[str, tuple[Callable, str]] = {
    "sma": (ta.sma, "close"),
    "ema": (ta.ema, "close"),
    "rsi": (ta.rsi, "close"),
    "atr": (ta.atr, "hlc"),
    "adx": (ta.adx, "hlc"),
    "bb_upper": (ta.bbands, "bb"),
    "bb_middle": (ta.bbands, "bb"),
    "bb_lower": (ta.bbands, "bb"),
}


def _is_dynamic(name: str) -> bool:
    """Return True when a name matches a dynamic indicator like sma_37."""
    for prefix in _DYNAMIC_HANDLERS:
        if name.startswith(f"{prefix}_"):
            rest = name[len(prefix) + 1 :]
            return rest.isdigit() and int(rest) >= 2
    return False


def _compute_dynamic(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Compute a dynamic period indicator and add its column to the frame."""
    for prefix, (func, source_col) in _DYNAMIC_HANDLERS.items():
        if name.startswith(f"{prefix}_"):
            period = int(name[len(prefix) + 1 :])
            if source_col == "hlc":
                result = func(df["high"], df["low"], df["close"], length=period)
                if result is None:
                    return df
                if isinstance(result, pd.Series):
                    # ta.atr returns a Series directly (single numeric column)
                    df[name] = result
                else:
                    # ta.adx returns a DataFrame with named columns
                    col = f"{prefix.upper()}_{period}"
                    if col in result.columns:
                        df[name] = result[col]
            elif source_col == "bb":
                result_df = func(df["close"], length=period, std=2)
                if result_df is not None:
                    bb_col = _extract_bb_column(result_df, prefix, period)
                    if bb_col:
                        df[name] = result_df[bb_col]
            else:
                df[name] = _safe_ta(func, df[source_col], length=period)
            return df
    return df


def _extract_bb_column(result_df, prefix: str, period: int) -> str | None:
    """Extract the correct Bollinger Band column from a pandas_ta result."""
    mapping = {"bb_upper": "BBU", "bb_middle": "BBM", "bb_lower": "BBL"}
    bb_prefix = mapping.get(prefix, "")
    if not bb_prefix:
        return None
    for col in result_df.columns:
        if col.startswith(f"{bb_prefix}_{period}"):
            return col
    return None


# ---------------------------------------------------------------------------
# Parameterized Rolling Volume Profile — vp_poc_Nd, vp_vah_Nd, vp_val_Nd
# ---------------------------------------------------------------------------


def _is_rolling_vp(name: str) -> bool:
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


def _compute_rolling_vp_dynamic(
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
