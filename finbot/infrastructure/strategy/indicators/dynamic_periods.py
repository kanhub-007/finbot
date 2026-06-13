"""Dynamic-period indicators — handles any period within supported ranges.

Resolves names like ``sma_37`` or ``atr_50`` that are not pre-registered.
Exposes ``is_dynamic`` and ``compute_dynamic`` consumed by the calculator.
No ``@register`` calls — these are dispatch helpers, not fixed handlers.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pandas_ta as ta

from finbot.infrastructure.strategy.indicator_registry import safe_ta

_DYNAMIC_HANDLERS: dict[str, tuple[Callable, str]] = {
    "sma": (ta.sma, "close"),
    "ema": (ta.ema, "close"),
    "rsi": (ta.rsi, "close"),
    "atr": (ta.atr, "hlc"),
    "adx": (ta.adx, "hlc"),
    "bb_upper": (ta.bbands, "bb"),
    "bb_middle": (ta.bbands, "bb"),
    "bb_lower": (ta.bbands, "bb"),
}


def is_dynamic(name: str) -> bool:
    """Return True when a name matches a dynamic indicator like sma_37."""
    for prefix in _DYNAMIC_HANDLERS:
        if name.startswith(f"{prefix}_"):
            rest = name[len(prefix) + 1 :]
            return rest.isdigit() and int(rest) >= 2
    return False


def compute_dynamic(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Compute a dynamic period indicator and add its column to the frame."""
    for prefix, (func, source_col) in _DYNAMIC_HANDLERS.items():
        if name.startswith(f"{prefix}_"):
            period = int(name[len(prefix) + 1 :])
            if source_col == "hlc":
                result = func(df["high"], df["low"], df["close"], length=period)
                if result is None:
                    return df
                if isinstance(result, pd.Series):
                    # ta.atr returns a Series directly (single numeric column)
                    df[name] = result
                else:
                    # ta.adx returns a DataFrame with named columns
                    col = f"{prefix.upper()}_{period}"
                    if col in result.columns:
                        df[name] = result[col]
            elif source_col == "bb":
                result_df = func(df["close"], length=period, std=2)
                if result_df is not None:
                    bb_col = _extract_bb_column(result_df, prefix, period)
                    if bb_col:
                        df[name] = result_df[bb_col]
            else:
                df[name] = safe_ta(func, df[source_col], length=period)
            return df
    return df


def _extract_bb_column(result_df, prefix: str, period: int) -> str | None:
    """Extract the correct Bollinger Band column from a pandas_ta result."""
    mapping = {"bb_upper": "BBU", "bb_middle": "BBM", "bb_lower": "BBL"}
    bb_prefix = mapping.get(prefix, "")
    if not bb_prefix:
        return None
    for col in result_df.columns:
        if col.startswith(f"{bb_prefix}_{period}"):
            return col
    return None
