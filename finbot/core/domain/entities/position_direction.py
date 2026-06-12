"""Position direction value object."""

from enum import StrEnum


class PositionDirection(StrEnum):
    """Current position direction for a symbol."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"
