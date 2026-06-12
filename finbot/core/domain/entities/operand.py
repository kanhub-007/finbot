"""Operand entity for JSON strategy conditions."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Operand:
    """A typed value used on either side of a strategy condition."""

    kind: str
    """Operand kind: field, indicator, feature, param, literal, or column."""

    value: Any
    """Operand value. For column-like operands this is the resolved bar key."""

    label: str = ""
    """Original human-readable alias or expression used for explanations."""

    sources: list[str] = field(default_factory=list)
    """Ordered fallback column names. The evaluator tries value first, then
    each source in order, returning the first non-None bar value."""
