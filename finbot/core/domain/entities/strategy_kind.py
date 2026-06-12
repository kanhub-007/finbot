"""StrategyKind enum — categorizes where a strategy comes from."""

from enum import Enum


class StrategyKind(Enum):
    """Identifies the source of a trading strategy definition."""

    BUILTIN = "builtin"
    """Strategy implemented as a Python class in the codebase."""

    USER_DEFINED = "user_defined"
    """JSON strategy document stored in strategy_documents table."""
