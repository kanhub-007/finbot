"""Tests for the pandas indicator engine with AMT strategy requirements."""

import numpy as np
import pandas as pd
import pytest

from finbot.core.domain.services.amt_signals import compute_amt_signals
from finbot.core.domain.services.auction_state import classify_auction_state
from finbot.core.domain.services.volume_profile import (
    compute_all_session_volume_profiles,
)


def _make_ohlcv_bars(n: int = 48) -> pd.DataFrame:
    """Build synthetic OHLCV bars with a sine-wave price pattern."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2025-01-02 09:30", periods=n, freq="1h")
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.1, 0.5, n)
    low = close - rng.uniform(0.1, 0.5, n)
    open_ = low + rng.uniform(0, 1, n) * (high - low)
    volume = rng.integers(1000, 5000, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


class TestIndicatorEngine:
    @pytest.fixture(scope="class")
    def bars(self) -> pd.DataFrame:
        return _make_ohlcv_bars(96)

    def test_volume_profile_columns_are_added(self, bars) -> None:
        result = compute_all_session_volume_profiles(bars)
        for col in ("vp_poc", "vp_vah", "vp_val"):
            assert col in result.columns
        # At least some values should be non-NaN.
        assert result["vp_poc"].notna().any()

    def test_auction_state_columns_are_added(self, bars) -> None:
        vp_bars = compute_all_session_volume_profiles(bars)
        result = classify_auction_state(vp_bars)
        for col in (
            "inside_value",
            "above_value",
            "below_value",
            "value_area_width_pct",
        ):
            assert col in result.columns

    def test_above_value_is_boolean(self, bars) -> None:
        vp_bars = compute_all_session_volume_profiles(bars)
        result = classify_auction_state(vp_bars)
        unique = set(result["above_value"].dropna().unique())
        assert unique <= {True, False}

    def test_acceptance_into_value_is_boolean(self, bars) -> None:
        vp_bars = compute_all_session_volume_profiles(bars)
        auction_bars = classify_auction_state(vp_bars)
        # Compute ATR first (needed by AMT signals).
        auction_bars["atr"] = (
            (auction_bars["high"] - auction_bars["low"]).rolling(14).mean()
        )
        result = compute_amt_signals(auction_bars)
        unique = set(result["acceptance_into_value"].dropna().unique())
        assert unique <= {True, False}

    def test_value_area_width_pct_is_added_for_v2(self, bars) -> None:
        vp_bars = compute_all_session_volume_profiles(bars)
        result = classify_auction_state(vp_bars)
        assert "value_area_width_pct" in result.columns
        # Should be non-negative.
        valid = result["value_area_width_pct"].dropna()
        assert (valid >= 0).all()

    def test_indicator_engine_returns_latest_enriched_bar(self, bars) -> None:
        vp_bars = compute_all_session_volume_profiles(bars)
        result = classify_auction_state(vp_bars)
        # Last row should have all columns populated.
        last = result.iloc[-1]
        for col in ("vp_vah", "vp_val", "above_value", "inside_value"):
            assert not pd.isna(last[col]), f"{col} is NaN on last bar"

    def test_empty_bars_returns_empty_result(self) -> None:
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = compute_all_session_volume_profiles(empty)
        assert len(result) == 0

    def test_not_enough_warmup_bars_produces_nans_or_empty(self) -> None:
        """A single short session may produce values or NaNs depending
        on bar distribution. Either is acceptable at warmup stage."""
        few = _make_ohlcv_bars(2)
        result = compute_all_session_volume_profiles(few)
        assert len(result) == 2
