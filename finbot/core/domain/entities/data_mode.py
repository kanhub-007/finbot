"""DataMode enum — whether a strategy uses proxy or real indicators."""

from enum import Enum


class DataMode(Enum):
    """Whether a strategy uses proxy (daily) or real (intraday) indicators."""

    PROXY = "proxy"
    REAL = "real"
