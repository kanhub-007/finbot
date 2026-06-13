"""Tests for the vectorised volume-profile aggregation (P2/P10 optimisation).

Asserts the vectorised batch distributor matches the per-bar reference and
that rolling-window VP fills the right rows.
"""

import numpy as np
import pandas as pd
import pytest

from finbot.core.domain.services.volume_profile import (
    _distribute_bar_volume,
    _distribute_bars_volume_vectorised,
    compute_rolling_window_vp,
    compute_session_volume_profile,
)


def _bars(n=30, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.1, 0.6, n)
    low = close - rng.uniform(0.1, 0.6, n)
    volume = rng.integers(100, 1000, n).astype(float)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": volume},
        index=pd.date_range("2025-01-02 09:30", periods=n, freq="1h"),
    )


def test_vectorised_distribution_matches_per_bar_reference() -> None:
    """The batch vectorised distributor must equal summing per-bar results."""
    df = _bars(40)
    price_buckets = np.linspace(98, 102, 100)
    bucket_size = price_buckets[1] - price_buckets[0]

    ref = np.zeros(100)
    for _, bar in df.iterrows():
        ref += _distribute_bar_volume(
            float(bar["high"]),
            float(bar["low"]),
            float(bar["close"]),
            float(bar["volume"]),
            price_buckets,
            bucket_size,
        )

    vec = _distribute_bars_volume_vectorised(
        df["high"].to_numpy(),
        df["low"].to_numpy(),
        df["close"].to_numpy(),
        df["volume"].to_numpy(),
        price_buckets,
        bucket_size,
    ).sum(axis=0)

    assert np.allclose(ref, vec, atol=1e-9)


def test_session_profile_poc_within_range() -> None:
    """POC/VAH/VAL from the vectorised path sit inside the session range."""
    df = _bars(50)
    profile = compute_session_volume_profile(df, num_buckets=100)
    assert df["low"].min() - 1 <= profile.poc <= df["high"].max() + 1
    assert profile.val <= profile.poc <= profile.vah


def test_rolling_window_vp_fills_trailing_rows_only() -> None:
    """rvp_* columns are NaN for the first window-1 bars, then populated."""
    df = _bars(30)
    result = compute_rolling_window_vp(df, window_bars=10, num_buckets=50)
    col = "rvp_poc_10"
    assert col in result.columns
    assert result[col].iloc[:9].isna().all()
    assert result[col].iloc[9:].notna().all()


def test_vectorised_handles_degenerate_flat_bars() -> None:
    """M3: flat bars (high==low) must keep their volume at the nearest bucket,
    matching the per-bar reference, instead of dropping it."""
    price_buckets = np.linspace(95, 105, 50)
    bucket_size = price_buckets[1] - price_buckets[0]

    # Two flat bars at 100.0, each with volume 50.
    highs = np.array([100.0, 100.0])
    lows = np.array([100.0, 100.0])
    closes = np.array([100.0, 100.0])
    volumes = np.array([50.0, 50.0])

    vec = _distribute_bars_volume_vectorised(
        highs, lows, closes, volumes, price_buckets, bucket_size
    )
    # Total volume preserved (100), concentrated in one bucket per bar.
    assert vec.sum() == pytest.approx(100.0)
    # Each flat bar's volume sits in a single bucket.
    for row in vec:
        nonzero = row[row > 0]
        assert len(nonzero) == 1
        assert nonzero[0] == pytest.approx(50.0)
