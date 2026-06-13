"""PandasTaIndicatorCalculator — pandas_ta implementation of IndicatorCalculator.

Calculates technical indicators (RSI, SMA, MACD, ATR, etc.) on OHLCV
DataFrames using the pandas_ta library and the shared indicator registry.

Implements the IndicatorCalculator domain interface via the Strategy pattern.
Individual indicator functions live in ``indicators/definitions.py``.
"""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta  # noqa: F401 — used by indicator modules

from finbot.core.domain.interfaces.indicator_calculator import (
    IndicatorCalculator,
)
from finbot.infrastructure.strategy import (
    indicators as _indicators_mod,  # noqa: F401 — triggers registrations
)
from finbot.infrastructure.strategy.indicator_registry import (
    _INDICATOR_HANDLERS,
    MIN_BARS,
    logger,
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
