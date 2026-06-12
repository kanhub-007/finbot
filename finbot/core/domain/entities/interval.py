"""Time interval for OHLCV price bars."""

from enum import StrEnum


class Interval(StrEnum):
    """Time interval for price bars."""

    MINUTE_5 = "5min"
    MINUTE_30 = "30min"
    HOUR_1 = "1h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
