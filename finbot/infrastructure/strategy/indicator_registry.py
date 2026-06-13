"""Indicator function registry — shared by the calculator and its modules.

Each indicator function is decorated with ``@register(name)`` and added
to ``_INDICATOR_HANDLERS``.  The calculator looks up handlers by name
at call time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import pandas as pd
import pandas_ta as ta  # noqa: F401 — used by indicator modules

logger = logging.getLogger(__name__)
MIN_BARS = 10

_INDICATOR_HANDLERS: dict[str, tuple[Callable, set[str]]] = {}


def register(name: str, requires: set[str] | None = None):
    """Decorator to register an indicator handler."""

    def decorator(func: Callable):
        _INDICATOR_HANDLERS[name] = (func, requires or set())
        return func

    return decorator


def safe_ta(func: Callable, *args, **kwargs) -> pd.Series | None:
    """Call a pandas_ta function and return None-safe result.

    pandas_ta returns None when there are fewer bars than the requested
    period length.  This helper converts None to a NaN-filled Series.
    """
    try:
        result = func(*args, **kwargs)
    except Exception:
        result = None
    if result is None:
        series = args[0] if args else kwargs.get("close")
        if series is not None and isinstance(series, pd.Series):
            return pd.Series(float("nan"), index=series.index, dtype="float64")
        return None
    return result
