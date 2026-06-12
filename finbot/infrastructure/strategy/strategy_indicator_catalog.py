"""StrategyIndicatorCatalog - supported indicator metadata for strategies."""

from finbot.core.domain.interfaces.indicator_capability_provider import (
    IndicatorCapabilityProvider,
)


class StrategyIndicatorCatalog(IndicatorCapabilityProvider):
    """Catalog of indicator columns currently supported by Finbar."""

    _PERIOD_RANGES = {
        "sma": (2, 500),
        "ema": (2, 500),
        "rsi": (2, 100),
    }
    _OPTIONAL_PERIOD_RANGES = {
        "atr": (2, 200),
        "adx": (2, 100),
        "bb_upper": (2, 200),
        "bb_middle": (2, 200),
        "bb_lower": (2, 200),
    }
    _FIXED = {
        "atr": "atr",
        "adx": "adx",
        "vwap": "vwap",
        # --- VWAP Standard Deviation Bands (Auction Market Theory) ---
        "vwap_session": "vwap_session",
        "vwap_upper_1": "vwap_upper_1",
        "vwap_lower_1": "vwap_lower_1",
        "vwap_upper_2": "vwap_upper_2",
        "vwap_lower_2": "vwap_lower_2",
        # --- Proxy Volume Profile (Auction Market Theory) ---
        "vp_poc": "vp_poc",
        "vp_vah": "vp_vah",
        "vp_val": "vp_val",
        # --- Rolling / Composite Value Areas ---
        "vp_poc_5d": "vp_poc_5d",
        "vp_vah_5d": "vp_vah_5d",
        "vp_val_5d": "vp_val_5d",
        "vp_poc_20d": "vp_poc_20d",
        "vp_vah_20d": "vp_vah_20d",
        "vp_val_20d": "vp_val_20d",
        # --- Rolling-window Volume Profile - bar-based (crypto / 24-7) ---
        "rvp_poc_48": "rvp_poc_48",
        "rvp_vah_48": "rvp_vah_48",
        "rvp_val_48": "rvp_val_48",
        "rvp_poc_96": "rvp_poc_96",
        "rvp_vah_96": "rvp_vah_96",
        "rvp_val_96": "rvp_val_96",
        "rvp_poc_336": "rvp_poc_336",
        "rvp_vah_336": "rvp_vah_336",
        "rvp_val_336": "rvp_val_336",
        # --- Composite Volume Profile - true stacked multi-session ---
        "cvp_poc_5d": "cvp_poc_5d",
        "cvp_vah_5d": "cvp_vah_5d",
        "cvp_val_5d": "cvp_val_5d",
        "cvp_poc_10d": "cvp_poc_10d",
        "cvp_vah_10d": "cvp_vah_10d",
        "cvp_val_10d": "cvp_val_10d",
        "cvp_poc_20d": "cvp_poc_20d",
        "cvp_vah_20d": "cvp_vah_20d",
        "cvp_val_20d": "cvp_val_20d",
        # --- Profile Shape Classifier ---
        "profile_shape": "profile_shape",
        # Profile Shape Boolean Wrappers
        "is_normal_shape": "is_normal_shape",
        "is_b_shape": "is_b_shape",
        "is_p_shape": "is_p_shape",
        "is_d_shape": "is_d_shape",
        "is_neutral_shape": "is_neutral_shape",
        # --- Coil / Squeeze Detector ---
        "is_coiled": "is_coiled",
        "coil_intensity": "coil_intensity",
        # --- Wyckoff Phase ---
        "wyckoff_phase": "wyckoff_phase",
        "poc_slope_5": "poc_slope_5",
        "poc_slope_20": "poc_slope_20",
        # Wyckoff Phase Boolean Wrappers
        "is_accumulation": "is_accumulation",
        "is_markup": "is_markup",
        "is_distribution": "is_distribution",
        "is_markdown": "is_markdown",
        "is_wyckoff_neutral": "is_wyckoff_neutral",
        # --- Market Profile - TPO-based (Auction Market Theory) ---
        "mp_poc": "mp_poc",
        "mp_vah": "mp_vah",
        "mp_val": "mp_val",
        # --- Auction State Classifiers (Auction Market Theory) ---
        "inside_value": "inside_value",
        "above_value": "above_value",
        "below_value": "below_value",
        "at_poc": "at_poc",
        "near_vah": "near_vah",
        "near_val": "near_val",
        "distance_to_vah_pct": "distance_to_vah_pct",
        "distance_to_val_pct": "distance_to_val_pct",
        "value_area_width_pct": "value_area_width_pct",
        "balance_status": "balance_status",
        # --- AMT Rule Signals (Auction Market Theory) ---
        "acceptance_into_value": "acceptance_into_value",
        "rejection_from_edge": "rejection_from_edge",
        "acceptance_outside_value": "acceptance_outside_value",
        "poc_rejection": "poc_rejection",
        "edge_volume_building": "edge_volume_building",
        "value_area_migration": "value_area_migration",
        "rvol": "rvol",
        "ibs": "ibs",
        "ker": "ker",
        "kama": "kama",
        "macd": "macd",
        "macd_signal": "macd_signal",
        "macd_hist": "macd_hist",
        "bb_upper": "bb_upper",
        "bb_middle": "bb_middle",
        "bb_lower": "bb_lower",
        # --- Proxy quantitative indicators ---
        "proxy_atr": "proxy_atr",
        "proxy_vwap": "proxy_vwap",
        "proxy_ibs": "proxy_ibs",
        "proxy_ib_high": "proxy_ib_high",
        "proxy_ib_low": "proxy_ib_low",
        "proxy_expected_move": "proxy_expected_move",
        "proxy_parkinson": "proxy_parkinson",
        "proxy_garman_klass": "proxy_garman_klass",
        "proxy_rogers_satchell": "proxy_rogers_satchell",
        # --- Intraday session metrics (real, not proxy) ---
        "ib_high": "ib_high",
        "ib_low": "ib_low",
        "ib_range": "ib_range",
        # --- Volume buffer levels ---
        "vol_buffer_high": "vol_buffer_high",
        "vol_buffer_low": "vol_buffer_low",
        # --- Support / resistance ---
        "swing_high_20": "swing_high_20",
        "swing_low_20": "swing_low_20",
        "breakout_level": "breakout_level",
        "breakout_signal": "breakout_signal",
        "is_power_zone": "is_power_zone",
        "breakout_quality": "breakout_quality",
        # --- Trend classification ---
        "price_vs_sma20": "price_vs_sma20",
        "trend_direction": "trend_direction",
        "trend_strength": "trend_strength",
        "trend_status": "trend_status",
        # --- Initial Balance ---
        "ib_midpoint": "ib_midpoint",
    }

    # Rolling VP parameterized pattern: vp_poc_Nd, vp_vah_Nd, vp_val_Nd
    _ROLLING_VP_BASE = {"vp_poc", "vp_vah", "vp_val"}
    # Rolling-window VP (bar-based): rvp_poc_N, rvp_vah_N, rvp_val_N
    _RVP_BASE = {"rvp_poc", "rvp_vah", "rvp_val"}
    # Composite VP: cvp_poc_Nd, cvp_vah_Nd, cvp_val_Nd
    _CVP_BASE = {"cvp_poc", "cvp_vah", "cvp_val"}

    def resolve(self, indicator_type: str, period: int | None) -> str | None:
        """Resolve an indicator type/period to a concrete indicator column."""
        name = indicator_type.lower()
        if name in self._PERIOD_RANGES:
            min_p, max_p = self._PERIOD_RANGES[name]
            if isinstance(period, int) and min_p <= period <= max_p:
                return f"{name}_{period}"
            return None
        if name in self._OPTIONAL_PERIOD_RANGES:
            min_p, max_p = self._OPTIONAL_PERIOD_RANGES[name]
            if period is None:
                return self._FIXED.get(name)
            if isinstance(period, int) and min_p <= period <= max_p:
                return f"{name}_{period}"
            return None
        return self._FIXED.get(name)

    def requires_period(self, indicator_type: str) -> bool:
        """Return True when the indicator type requires a period."""
        return indicator_type.lower() in self._PERIOD_RANGES

    def accepts_period(self, indicator_type: str) -> bool:
        """Return True when the indicator type accepts a period argument."""
        name = indicator_type.lower()
        return name in self._PERIOD_RANGES or name in self._OPTIONAL_PERIOD_RANGES

    def supports_concrete(self, name: str) -> bool:
        """Return True when a concrete indicator column is known."""
        if name in self._FIXED or name in self._FIXED.values():
            return True
        for suffix in ("_1d", "_1h", "_30min", "_5min", "_1w"):
            if name.endswith(suffix):
                return self.supports_concrete(name[: -len(suffix)])
        # Parameterized rolling VP: vp_poc_Nd, vp_vah_Nd, vp_val_Nd
        for base in self._ROLLING_VP_BASE:
            prefix = f"{base}_"
            if name.startswith(prefix) and name.endswith("d"):
                inner = name[len(prefix) : -1]
                if inner.isdigit() and int(inner) >= 1:
                    return True
        # Parameterized rolling-window VP: rvp_poc_N, rvp_vah_N, rvp_val_N
        for base in self._RVP_BASE:
            prefix = f"{base}_"
            if name.startswith(prefix):
                inner = name[len(prefix) :]
                if inner.isdigit() and int(inner) >= 1:
                    return True
        # Parameterized composite VP: cvp_poc_Nd, cvp_vah_Nd, cvp_val_Nd
        for base in self._CVP_BASE:
            prefix = f"{base}_"
            if name.startswith(prefix) and name.endswith("d"):
                inner = name[len(prefix) : -1]
                if inner.isdigit() and int(inner) >= 1:
                    return True
        for prefix in self._PERIOD_RANGES:
            if name.startswith(f"{prefix}_"):
                rest = name[len(prefix) + 1 :]
                if rest.isdigit():
                    return True
        for prefix in self._OPTIONAL_PERIOD_RANGES:
            if name.startswith(f"{prefix}_"):
                rest = name[len(prefix) + 1 :]
                if rest.isdigit():
                    return True
        return False

    def supported_concrete_names(self) -> list[str]:
        """Return all concrete indicator columns currently supported."""
        names = list(self._FIXED.values())
        for indicator_type, (min_p, max_p) in self._PERIOD_RANGES.items():
            names.extend(
                f"{indicator_type}_{period}"
                for period in range(min_p, min(min_p + 5, max_p + 1))
            )
        for indicator_type, (min_p, max_p) in self._OPTIONAL_PERIOD_RANGES.items():
            names.extend(
                f"{indicator_type}_{period}"
                for period in range(min_p, min(min_p + 3, max_p + 1))
            )
        return sorted(names)

    def as_dict(self) -> dict:
        """Return a JSON-serializable capabilities payload."""
        period_ranges = {
            key: {"min": min_p, "max": max_p, "required": True}
            for key, (min_p, max_p) in self._PERIOD_RANGES.items()
        }
        optional_ranges = {
            key: {"min": min_p, "max": max_p, "required": False}
            for key, (min_p, max_p) in self._OPTIONAL_PERIOD_RANGES.items()
        }
        period_ranges.update(optional_ranges)
        return {
            "schema_version": "2.0",
            "parameterized_indicators_enabled": True,
            "period_ranges": period_ranges,
            "rolling_vp_windows": (
                "vp_poc_Nd, vp_vah_Nd, vp_val_Nd "
                "for any session window N >= 1 "
                "(e.g. vp_poc_10d, vp_vah_50d, vp_val_100d). "
                "cvp_poc_Nd, cvp_vah_Nd, cvp_val_Nd "
                "for true composite (stacked) N-session window. "
                "rvp_poc_N, rvp_vah_N, rvp_val_N "
                "for any bar window N >= 1 "
                "(e.g. rvp_poc_48, rvp_vah_336 - for crypto/24-7 markets)."
            ),
            "fixed_indicators": sorted(self._FIXED),
            "supported_concrete_names": (
                "any period within ranges for sma/ema/rsi/atr/adx"
            ),
        }
