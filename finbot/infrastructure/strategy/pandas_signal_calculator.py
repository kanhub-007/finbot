"""PandasSignalCalculator — pandas implementation of SignalCalculator.

Computes signal interpretation columns from enriched OHLCV DataFrames.
Uses the ConfidenceScorer domain service for pure scoring logic.
"""

from __future__ import annotations

import pandas as pd

from finbot.core.domain.entities.risk_factor import RiskFactor
from finbot.core.domain.entities.rsi_zone import RsiZone
from finbot.core.domain.interfaces.signal_calculator import SignalCalculator
from finbot.core.domain.services.confidence_scorer import ConfidenceScorer


class PandasSignalCalculator(SignalCalculator):
    """Add signal interpretation columns to a pandas DataFrame."""

    def __init__(self, scorer: ConfidenceScorer | None = None):
        """Create the calculator with an optional domain scorer."""
        self._scorer = scorer or ConfidenceScorer()

    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Compute all signal columns and return the enriched frame."""
        result = frame.copy()
        result["rsi_zone"] = self._compute_rsi_zone(result)
        result["is_extreme_oversold"] = result["rsi_zone"] == RsiZone.EXTREME_OVERSOLD
        result["is_extreme_overbought"] = (
            result["rsi_zone"] == RsiZone.EXTREME_OVERBOUGHT
        )
        result["is_overextended"] = (
            result["is_extreme_oversold"] | result["is_extreme_overbought"]
        )
        result["adx_conviction"] = self._compute_adx_conviction(result)
        result["is_weak_trend"] = result.get("adx", 0) < 20
        result["is_squeeze"] = self._compute_squeeze(result)
        result["near_resistance"] = self._compute_near_resistance(result)
        result["near_support"] = self._compute_near_support(result)
        result["is_low_volume"] = result.get("rvol", 1.0) < 0.5
        result["confidence_score"] = self._compute_confidence(result)
        return result

    # ── column calculators ────────────────────────────────────────────

    @staticmethod
    def _compute_rsi_zone(df: pd.DataFrame) -> pd.Series:
        rsi = df.get("rsi_14", pd.Series(50, index=df.index))
        conditions = [
            (rsi < 20, RsiZone.EXTREME_OVERSOLD),
            (rsi < 30, RsiZone.OVERSOLD),
            (rsi <= 70, RsiZone.NEUTRAL),
            (rsi <= 80, RsiZone.OVERBOUGHT),
        ]
        result = pd.Series(RsiZone.EXTREME_OVERBOUGHT, index=df.index, dtype="object")
        for cond, zone in reversed(conditions):
            result = result.where(~cond, zone)
        return result

    @staticmethod
    def _compute_adx_conviction(df: pd.DataFrame) -> pd.Series:
        adx = df.get("adx", pd.Series(0, index=df.index))
        conditions = [
            (adx < 15, 20),
            (adx < 20, 35),
            (adx < 25, 50),
            (adx < 35, 70),
            (adx < 50, 85),
        ]
        result = pd.Series(95, index=df.index, dtype="float64")
        for cond, val in reversed(conditions):
            result = result.where(~cond, float(val))
        return result

    @staticmethod
    def _compute_squeeze(df: pd.DataFrame) -> pd.Series:
        bb_upper = df.get("bb_upper_20")
        bb_lower = df.get("bb_lower_20")
        adx = df.get("adx")
        close = df.get("close")
        if bb_upper is None or bb_lower is None or adx is None or close is None:
            return pd.Series(False, index=df.index)
        bb_width_pct = (bb_upper - bb_lower) / close.replace(0, pd.NA)
        return (bb_width_pct < 0.03) & (adx < 20)

    @staticmethod
    def _compute_near_resistance(df: pd.DataFrame) -> pd.Series:
        close = df.get("close")
        swing_high = df.get("swing_high_20")
        atr = df.get("atr")
        if close is None or swing_high is None or atr is None:
            return pd.Series(False, index=df.index)
        valid = (swing_high > 0) & (atr > 0)
        distance = (close - swing_high).abs()
        return valid & (distance < 0.5 * atr)

    @staticmethod
    def _compute_near_support(df: pd.DataFrame) -> pd.Series:
        close = df.get("close")
        swing_low = df.get("swing_low_20")
        atr = df.get("atr")
        if close is None or swing_low is None or atr is None:
            return pd.Series(False, index=df.index)
        valid = (swing_low > 0) & (atr > 0)
        distance = (close - swing_low).abs()
        return valid & (distance < 0.5 * atr)

    def _compute_confidence(self, df: pd.DataFrame) -> pd.Series:
        """Row‑wise confidence scoring — calls the domain scorer per row.

        This is intentionally per‑row (not vectorised) because
        ConfidenceScorer is a pure domain service, not pandas‑aware.
        For typical backtest frame sizes (500–2,000 rows) this is fine.
        """
        scores: list[int] = []
        for idx in range(len(df)):
            row = df.iloc[idx]
            risk_factors = self._gather_risk_factors(row)
            result = self._scorer.score(
                adx=float(row.get("adx", 0) or 0),
                direction=str(row.get("trend_direction", "")),
                rvol=float(row.get("rvol", 0) or 0),
                is_power_zone=bool(row.get("is_power_zone", False)),
                risk_factors=risk_factors,
            )
            scores.append(result.score)
        return pd.Series(scores, index=df.index, dtype="float64")

    @staticmethod
    def _gather_risk_factors(row: pd.Series) -> list[str]:
        factors: list[str] = []
        adx = float(row.get("adx", 0) or 0)
        rsi = float(row.get("rsi_14", 50) or 50)
        rvol = float(row.get("rvol", 1.0) or 1.0)

        if adx < 20:
            factors.append(RiskFactor.WEAK_TREND)
        if rvol < 0.5:
            factors.append(RiskFactor.LOW_VOLUME)
        if rsi > 80:
            factors.append(RiskFactor.OVEREXTENDED_UP)
        elif rsi < 20:
            factors.append(RiskFactor.OVEREXTENDED_DOWN)
        if row.get("near_resistance"):
            factors.append(RiskFactor.NEAR_RESISTANCE)
        if row.get("near_support"):
            factors.append(RiskFactor.NEAR_SUPPORT)
        if row.get("is_squeeze"):
            factors.append(RiskFactor.BB_SQUEEZE)
        return factors
