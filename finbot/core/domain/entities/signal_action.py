"""Signal action value object."""

from enum import StrEnum


class SignalAction(StrEnum):
    """Normalized action produced by strategy evaluation."""

    HOLD = "hold"
    LONG_ENTRY = "long_entry"
    SHORT_ENTRY = "short_entry"
    LONG_EXIT = "long_exit"
    SHORT_EXIT = "short_exit"
