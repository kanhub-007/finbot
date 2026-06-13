"""Shared helpers for indicator modules — lazy domain-service imports.

Holds the lazy-import aliases used by several indicator modules so the heavy
non-AMT domain services (Wyckoff, profile-shape, market-profile, coil, proxy,
composite-VP, vwap-bands) are only imported on first use, keeping registration
import cheap.  No indicator registrations happen here.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable


def lazy_import(module_name: str, attr: str) -> Callable:
    """Return a callable that imports ``attr`` from a domain service on first use.

    The target module is ``finbot.core.domain.services.{module_name}``.
    """

    def _wrapper(*args, **kwargs):
        mod = importlib.import_module(f"finbot.core.domain.services.{module_name}")
        return getattr(mod, attr)(*args, **kwargs)

    cached: dict[str, Callable] = {}

    def _lazy(*args, **kwargs):
        if "fn" not in cached:
            cached["fn"] = _wrapper
        return cached["fn"](*args, **kwargs)

    return _lazy


# --- Lazy aliases for heavy domain services -------------------------------
# Each is resolved on first call, then cached for subsequent calls.

compute_vwap_session_bands = lazy_import("vwap_bands", "compute_vwap_session_bands")
classify_wyckoff_phase = lazy_import("wyckoff_phase", "classify_wyckoff_phase")
compute_is_accumulation = lazy_import("wyckoff_wrappers", "compute_is_accumulation")
compute_is_markup = lazy_import("wyckoff_wrappers", "compute_is_markup")
compute_is_distribution = lazy_import("wyckoff_wrappers", "compute_is_distribution")
compute_is_markdown = lazy_import("wyckoff_wrappers", "compute_is_markdown")
compute_is_wyckoff_neutral = lazy_import(
    "wyckoff_wrappers", "compute_is_wyckoff_neutral"
)
compute_composite_vp = lazy_import("composite_vp", "compute_composite_vp")
classify_all_profile_shapes = lazy_import(
    "profile_shape", "classify_all_profile_shapes"
)
compute_is_b_shape = lazy_import("profile_shape_wrappers", "compute_is_b_shape")
compute_is_d_shape = lazy_import("profile_shape_wrappers", "compute_is_d_shape")
compute_is_neutral_shape = lazy_import(
    "profile_shape_wrappers", "compute_is_neutral_shape"
)
compute_is_normal_shape = lazy_import(
    "profile_shape_wrappers", "compute_is_normal_shape"
)
compute_is_p_shape = lazy_import("profile_shape_wrappers", "compute_is_p_shape")
enrich_dataframe_with_proxies = lazy_import(
    "proxy_indicator", "enrich_dataframe_with_proxies"
)
compute_all_session_market_profiles = lazy_import(
    "market_profile", "compute_all_session_market_profiles"
)
detect_coil = lazy_import("coil_detector", "detect_coil")
