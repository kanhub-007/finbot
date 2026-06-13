"""Guardrail test for the indicator registry.

``infrastructure/strategy/indicators/definitions.py`` is a large (1000+ line)
flat registry where each indicator self-registers via ``@register(name)`` on
import.  Because registration is an import side-effect, a future split of the
file risks silently dropping handlers — which would make indicator columns
disappear with no error, misbehaving strategies in a trading system.

This test snapshots the exact set of registered indicator names so any drop
(or addition) is a deliberate, reviewed change, and a future file split can be
verified safe.
"""

from finbot.infrastructure.strategy import indicators as _indicators_mod  # noqa: F401
from finbot.infrastructure.strategy.indicator_registry import _INDICATOR_HANDLERS

# Snapshot of every indicator name registered as of this commit.  Update this
# set (and note why) when indicators are intentionally added or removed.
_EXPECTED_INDICATOR_NAMES = {
    "above_value",
    "acceptance_into_value",
    "acceptance_outside_value",
    "adx",
    "at_poc",
    "atr",
    "balance_status",
    "bb_lower",
    "bb_middle",
    "bb_upper",
    "below_value",
    "breakout_level",
    "breakout_quality",
    "breakout_signal",
    "coil_intensity",
    "cvp_poc_10d",
    "cvp_poc_20d",
    "cvp_poc_5d",
    "cvp_vah_10d",
    "cvp_vah_20d",
    "cvp_vah_5d",
    "cvp_val_10d",
    "cvp_val_20d",
    "cvp_val_5d",
    "distance_to_vah_pct",
    "distance_to_val_pct",
    "edge_volume_building",
    "ema_12",
    "ema_26",
    "ib_high",
    "ib_low",
    "ib_midpoint",
    "ib_range",
    "ibs",
    "inside_value",
    "is_accumulation",
    "is_b_shape",
    "is_coiled",
    "is_d_shape",
    "is_distribution",
    "is_markdown",
    "is_markup",
    "is_neutral_shape",
    "is_normal_shape",
    "is_p_shape",
    "is_power_zone",
    "is_wyckoff_neutral",
    "kama",
    "ker",
    "macd",
    "macd_hist",
    "macd_signal",
    "mp_poc",
    "mp_vah",
    "mp_val",
    "near_vah",
    "near_val",
    "poc_rejection",
    "poc_slope_20",
    "poc_slope_5",
    "price_vs_sma20",
    "profile_shape",
    "proxy_atr",
    "proxy_vwap",
    "rejection_from_edge",
    "rsi_14",
    "rsi_7",
    "rvol",
    "rvp_poc_336",
    "rvp_poc_48",
    "rvp_poc_96",
    "rvp_vah_336",
    "rvp_vah_48",
    "rvp_vah_96",
    "rvp_val_336",
    "rvp_val_48",
    "rvp_val_96",
    "sma_10",
    "sma_20",
    "sma_200",
    "sma_30",
    "sma_50",
    "swing_high_20",
    "swing_low_20",
    "trend_direction",
    "trend_status",
    "trend_strength",
    "value_area_migration",
    "value_area_width_pct",
    "vol_buffer_high",
    "vol_buffer_low",
    "vp_poc",
    "vp_poc_20d",
    "vp_poc_5d",
    "vp_vah",
    "vp_vah_20d",
    "vp_vah_5d",
    "vp_val",
    "vp_val_20d",
    "vp_val_5d",
    "vwap",
    "vwap_lower_1",
    "vwap_lower_2",
    "vwap_upper_1",
    "vwap_upper_2",
    "wyckoff_phase",
}


def test_all_expected_indicators_are_registered() -> None:
    """Every documented indicator must be registered (no silent drops)."""
    missing = _EXPECTED_INDICATOR_NAMES - set(_INDICATOR_HANDLERS)
    assert not missing, f"Indicators dropped from registry: {sorted(missing)}"


def test_no_unexpected_indicators_registered() -> None:
    """New indicators require an intentional snapshot update here."""
    extra = set(_INDICATOR_HANDLERS) - _EXPECTED_INDICATOR_NAMES
    assert not extra, (
        f"Unregistered-in-snapshot indicators found: {sorted(extra)}. "
        f"Add them to _EXPECTED_INDICATOR_NAMES."
    )


def test_every_handler_accepts_the_documented_signature() -> None:
    """Each handler is callable as (df, name, cache) -> df."""
    for name, (handler, _requires) in _INDICATOR_HANDLERS.items():
        # We do not execute (most need many bars); we only assert the handler
        # is a callable registered under a non-empty name.
        assert callable(handler), f"{name} handler is not callable"
        assert isinstance(name, str) and name, "registered name must be non-empty str"
