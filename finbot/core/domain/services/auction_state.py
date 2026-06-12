"""Auction state classifiers — where is price relative to value area?

Pure functions that derive auction state from Volume Profile and VWAP
bands data. Answers the AMT questions: inside/outside value, near edges,
balance vs imbalance, and value area characteristics.

All functions are pure — no state, no I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def classify_auction_state(df: pd.DataFrame) -> pd.DataFrame:
    """Add auction state columns derived from Volume Profile and VWAP bands.

    Requires these columns to already exist on the DataFrame:
      - vp_poc, vp_vah, vp_val (from Volume Profile)
      - close (from OHLCV)
      - atr (optional, for balance detection)

    Adds columns:
      - inside_value:      bool   — close between VAL and VAH
      - above_value:       bool   — close > VAH
      - below_value:       bool   — close < VAL
      - at_poc:            bool   — close within 2% of POC (of value area)
      - near_vah:          bool   — close within 10% of VAH (of value area width)
      - near_val:          bool   — close within 10% of VAL (of value area width)
      - distance_to_vah_pct: float — (VAH - close) / VAH * 100
      - distance_to_val_pct: float — (close - VAL) / close * 100
      - value_area_width_pct: float — (VAH - VAL) / VAH * 100
      - balance_status:    str    — BALANCED | IMBALANCED_UP | IMBALANCED_DOWN
    """
    result = df.copy()

    close = result["close"]
    vah = result.get("vp_vah", pd.Series(np.nan, index=result.index))
    val = result.get("vp_val", pd.Series(np.nan, index=result.index))
    poc = result.get("vp_poc", pd.Series(np.nan, index=result.index))

    # --- Position relative to value area ---
    result["inside_value"] = (close >= val) & (close <= vah)
    result["above_value"] = close > vah
    result["below_value"] = close < val

    # --- Proximity to POC ---
    value_width = vah - val  # noqa: F841
    poc_distance = (close - poc).abs()
    # Within 2% of value area width from POC
    result["at_poc"] = poc_distance <= (value_width * 0.02)

    # --- Proximity to edges ---
    vah_distance = (vah - close).abs()
    val_distance = (close - val).abs()
    # Within 10% of value area width from edge
    result["near_vah"] = vah_distance <= (value_width * 0.10)
    result["near_val"] = val_distance <= (value_width * 0.10)

    # --- Distance percentages ---
    result["distance_to_vah_pct"] = np.where(vah > 0, (vah - close) / vah * 100.0, 0.0)
    result["distance_to_val_pct"] = np.where(
        close > 0, (close - val) / close * 100.0, 0.0
    )
    result["value_area_width_pct"] = np.where(vah > 0, value_width / vah * 100.0, 0.0)

    # --- Balance status ---
    result["balance_status"] = _detect_balance(result)

    return result


def _detect_balance(df: pd.DataFrame) -> pd.Series:
    """Classify each bar as BALANCED or IMBALANCED.

    BALANCED:
      - Price is inside the value area, AND
      - Value area width < 1.5 × ATR (narrow range = agreement on value)

    IMBALANCED_UP:
      - Price is above VAH, OR
      - Price is inside value but width > 1.5 × ATR AND recent
        direction (5-bar close change) is positive

    IMBALANCED_DOWN:
      - Price is below VAL, OR
      - Price is inside value but width > 1.5 × ATR AND recent
        direction is negative
    """
    inside = df["inside_value"]
    above = df["above_value"]
    below = df["below_value"]
    value_width = df["vp_vah"] - df["vp_val"]
    atr = df.get("atr", pd.Series(np.nan, index=df.index))

    # Default: BALANCED
    result = pd.Series("BALANCED", index=df.index, dtype="object")

    # IMBALANCED: price outside value area
    result[above] = "IMBALANCED_UP"
    result[below] = "IMBALANCED_DOWN"

    # Wide value area with directional bias (inside but disagreement)
    if atr.notna().any():
        wide_area = value_width > (atr * 1.5)
        recent_direction = df["close"] - df["close"].shift(5)

        # Inside value but wide and trending up → imbalanced up
        wide_up = inside & wide_area & (recent_direction > 0)
        result[wide_up] = "IMBALANCED_UP"

        # Inside value but wide and trending down → imbalanced down
        wide_down = inside & wide_area & (recent_direction < 0)
        result[wide_down] = "IMBALANCED_DOWN"

    return result
