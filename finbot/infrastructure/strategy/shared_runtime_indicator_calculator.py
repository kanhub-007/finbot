"""Adapter: package PandasTaIndicatorCalculator -> Finbot IndicatorCalculator.

Thin delegation so Finbot depends on its own IndicatorCalculator
interface; the package import (pandas/numpy-backed) lives in
infrastructure only. The package calculator is stateless — it
recomputes all columns from the full frame each call, so the caller
must pass the complete warmup frame (Finbot's cached enriched frame),
never just the latest bar.
"""

from typing import Any

from finbar_strategy_runtime.indicators.pandas_ta_indicator_calculator import (
    PandasTaIndicatorCalculator as _PackageCalculator,
)

from finbot.core.domain.interfaces.indicator_calculator import IndicatorCalculator


class SharedRuntimeIndicatorCalculator(IndicatorCalculator):
    """Thin delegation to the shared package indicator engine."""

    def __init__(self) -> None:
        self._calc = _PackageCalculator()

    def calculate(self, df: Any, indicators: list[str]) -> Any:
        """Apply requested indicators and return the enriched frame."""
        return self._calc.calculate(df, indicators)
