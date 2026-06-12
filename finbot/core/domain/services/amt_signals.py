"""AMT Rule Signals — encodes the 5 Auction Market Theory rules as boolean signals.

Pure functions that derive actionable signals from Volume Profile and
auction state data. No forward-looking bias — all signals use only
current and past bar data (shift(1), never shift(-1)).

AMT Rules encoded:
  Rule 1: acceptance_into_value   — price enters value from outside, held
  Rule 2: rejection_from_edge     — price touches edge and reverses (inside balance)
  Rule 3: acceptance_outside_value — price leaves value, held outside (seeks new value)
  Rule 4: poc_rejection           — strong reversal from POC
  Rule 5: edge_volume_building    — volume accumulating at edge (genuine breakout setup)

All functions are pure — no state, no I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_amt_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all AMT rule signals from enriched bar data.

    Requires these columns to already exist:
      - vp_poc, vp_vah, vp_val (Volume Profile)
      - close (OHLCV)
      - rvol (relative volume)
      - atr (average true range)
      - inside_value, above_value, below_value (auction state)

    Adds columns:
      - acceptance_into_value:      bool
      - rejection_from_edge:        bool
      - acceptance_outside_value:   bool
      - poc_rejection:              bool
      - edge_volume_building:       bool
      - value_area_migration:       str — HIGHER | LOWER | STABLE
    """
    result = df.copy()

    result["acceptance_into_value"] = _acceptance_into_value(result)
    result["rejection_from_edge"] = _rejection_from_edge(result)
    result["acceptance_outside_value"] = _acceptance_outside_value(result)
    result["poc_rejection"] = _poc_rejection(result)
    result["edge_volume_building"] = _edge_volume_building(result)
    result["value_area_migration"] = _value_area_migration(result)

    return result


# ---------------------------------------------------------------------------
# AMT Rule 1: Price accepts into balance → likely to travel to other side
# ---------------------------------------------------------------------------


def _acceptance_into_value(df: pd.DataFrame) -> pd.Series:
    """Signal: price was outside value area, crossed into it.

    Previous bar's close was outside the session's value area,
    current bar's close is inside. No forward-looking bias.
    """
    prev_close = df["close"].shift(1)
    prev_vah = df["vp_vah"].shift(1)
    prev_val = df["vp_val"].shift(1)

    was_outside = (prev_close > prev_vah) | (prev_close < prev_val)
    now_inside = df["inside_value"]

    return was_outside & now_inside


# ---------------------------------------------------------------------------
# AMT Rule 2: Price inside balance → chops at edges
# ---------------------------------------------------------------------------


def _rejection_from_edge(df: pd.DataFrame) -> pd.Series:
    """Signal: price touched the edge of value and reversed.

    Current bar is near the edge (VAH or VAL), AND
    bar's IBS (internal bar strength) suggests rejection:
    - Near VAH + IBS < 0.3 → price closed near low (rejected from high)
    - Near VAL + IBS > 0.7 → price closed near high (rejected from low)
    """
    ibs = _compute_ibs(df)

    rejection_high = df["near_vah"] & (ibs < 0.3)
    rejection_low = df["near_val"] & (ibs > 0.7)

    return rejection_high | rejection_low


def _compute_ibs(df: pd.DataFrame) -> pd.Series:
    """Internal Bar Strength: (C - L) / (H - L).

    Uses pre-computed ibs column if available, otherwise computes inline.
    """
    if "ibs" in df.columns:
        return df["ibs"]
    bar_range = df["high"] - df["low"]
    return np.where(bar_range > 0, (df["close"] - df["low"]) / bar_range, 0.5)


# ---------------------------------------------------------------------------
# AMT Rule 3: Price accepts outside balance → seeks new value (old POC)
# ---------------------------------------------------------------------------


def _acceptance_outside_value(df: pd.DataFrame) -> pd.Series:
    """Signal: price was inside value area, crossed outside.

    Previous bar's close was inside the session's value area,
    current bar's close is outside. No forward-looking bias.

    Used as an entry signal: the market is now imbalanced and
    seeking a new fair value (often the POC of the prior balance).
    """
    prev_inside = df["inside_value"].shift(1)
    now_outside = df["above_value"] | df["below_value"]

    return prev_inside & now_outside


# ---------------------------------------------------------------------------
# AMT Rule 4: Strong POC reaction can disrupt the full rotation
# ---------------------------------------------------------------------------


def _poc_rejection(df: pd.DataFrame) -> pd.Series:
    """Signal: price reached POC and reversed strongly.

    Price is near POC, previous bar showed a strong move toward POC,
    and current bar shows reversal (IBS opposite to approach direction).

    This signals that Rule 1 (full rotation) may not complete.
    """
    at_poc = df["at_poc"]
    atr = df.get("atr", pd.Series(np.nan, index=df.index))

    if atr.isna().all():
        return pd.Series(False, index=df.index)

    # Strong move: price moved > 0.5 ATR toward POC
    price_change = df["close"] - df["close"].shift(1)
    poc_direction = df["vp_poc"] - df["close"].shift(1)
    strong_move_toward_poc = (np.sign(price_change) == np.sign(poc_direction)) & (
        price_change.abs() > atr * 0.5
    )

    # Reversal: current IBS opposite to approach
    ibs = _compute_ibs(df)
    approached_from_below = price_change.shift(1) > 0
    reversal_signal = (approached_from_below & (ibs < 0.3)) | (
        ~approached_from_below & (ibs > 0.7)
    )

    return at_poc & strong_move_toward_poc.shift(1) & reversal_signal


# ---------------------------------------------------------------------------
# AMT Rule 5: Volume builds at edge → genuine breakout setup
# ---------------------------------------------------------------------------


def _edge_volume_building(df: pd.DataFrame) -> pd.Series:
    """Signal: volume accumulating at the edge of value area.

    Price near VAH or VAL AND relative volume elevated (>1.0).
    This is the setup for a genuine breakout per AMT Rule 5.
    """
    near_edge = df["near_vah"] | df["near_val"]
    # Time component: price has been near edge for 2+ consecutive bars
    sustained = near_edge & near_edge.shift(1)
    rvol = df.get("rvol", pd.Series(1.0, index=df.index))
    elevated_volume = rvol > 1.0

    return sustained & elevated_volume


# ---------------------------------------------------------------------------
# Value Area Migration — tracks whether value is shifting
# ---------------------------------------------------------------------------


def _value_area_migration(df: pd.DataFrame) -> pd.Series:
    """Track whether the value area POC is migrating session-over-session.

    Compares current session's POC to the previous session's POC.
    Migrating POC = market is renegotiating fair value.

    Returns: 'HIGHER' | 'LOWER' | 'STABLE'
    """
    poc = df["vp_poc"]

    # Detect session changes via date boundary (robust, not POC comparison)
    date_series = pd.Series(
        pd.to_datetime(df.index).strftime("%Y-%m-%d"), index=df.index
    )
    session_change = date_series != date_series.shift(1)

    result = pd.Series("STABLE", index=df.index, dtype="object")

    # On session changes, compare POC to previous session's POC
    migration_up = session_change & (poc > poc.shift(1))
    migration_down = session_change & (poc < poc.shift(1))

    result[migration_up] = "HIGHER"
    result[migration_down] = "LOWER"

    # Forward-fill the migration status within each session (vectorized)
    result = result.where(session_change, pd.NA).ffill().fillna("STABLE")

    return result
