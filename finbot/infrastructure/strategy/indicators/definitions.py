"""Indicator definitions — aggregator that triggers registration of all handlers.

The actual indicator handlers live in sibling modules, grouped by category.
Importing this package triggers ``@register(name)`` side-effects in every
module so the calculator's ``_INDICATOR_HANDLERS`` dict is fully populated.

This file also re-exports the dynamic-dispatch helpers consumed directly by
``pandas_ta_indicator_calculator`` so that module's import path is unchanged.
"""

from __future__ import annotations

# Importing each module registers its handlers as a side-effect.
from finbot.infrastructure.strategy.indicators import (  # noqa: F401
    amt,
    auction,
    bands,
    breakout,
    inside_bars,
    market_profile,
    momentum,
    profile_analysis,
    trend,
    volatility,
    volume_profile,
)
from finbot.infrastructure.strategy.indicators._shared import (
    enrich_dataframe_with_proxies,
)
from finbot.infrastructure.strategy.indicators.dynamic_periods import (
    compute_dynamic as _compute_dynamic,
)
from finbot.infrastructure.strategy.indicators.dynamic_periods import (
    is_dynamic as _is_dynamic,
)
from finbot.infrastructure.strategy.indicators.volume_profile import (
    compute_rolling_vp_dynamic as _compute_rolling_vp_dynamic,
)
from finbot.infrastructure.strategy.indicators.volume_profile import (
    is_rolling_vp as _is_rolling_vp,
)

__all__ = [
    "_compute_dynamic",
    "_compute_rolling_vp_dynamic",
    "_is_dynamic",
    "_is_rolling_vp",
    "enrich_dataframe_with_proxies",
]
