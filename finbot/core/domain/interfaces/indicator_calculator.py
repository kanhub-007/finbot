"""Domain interface for technical indicator calculation.

Pure computation contract — implementations may use pandas_ta, TA-Lib,
or other backends. The use case depends on this interface, never on
a concrete implementation.
"""

from abc import ABC, abstractmethod
from typing import Any


class IndicatorCalculator(ABC):
    """Calculate technical indicators on OHLCV DataFrames.

    Takes a DataFrame with columns [open, high, low, close, volume]
    indexed by timestamp and a list of indicator names. Returns the
    same DataFrame with additional indicator columns.
    """

    @abstractmethod
    def calculate(self, df: Any, indicators: list[str]) -> Any:
        """Apply requested indicators and return enriched DataFrame.

        Args:
            df: DataFrame with columns [open, high, low, close, volume]
                and a datetime index.
            indicators: List of indicator names. Supported names include:
                - rsi_7, rsi_14
                - sma_10, sma_20, sma_50, sma_200
                - ema_12, ema_26
                - macd, macd_signal, macd_hist
                - atr
                - adx
                - vwap
                - bb_upper, bb_middle, bb_lower
                - rvol
                - ibs
                - proxy_typical_price, proxy_ohlc4, proxy_ibs, etc.

        Returns:
            DataFrame with original columns plus requested indicator columns.

        Raises:
            ValueError: If df is missing required columns.
        """
        ...
