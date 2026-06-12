"""Condition entity for JSON strategy rules."""

from dataclasses import dataclass

from finbot.core.domain.entities.operand import Operand


@dataclass(frozen=True)
class Condition:
    """An atomic comparison between operands.

    Examples include ``fast_sma crosses_above slow_sma`` and ``rsi < 30``.
    """

    left: Operand
    """Left-hand side operand."""

    operator: str
    """Comparison operator."""

    right: Operand | None = None
    """Optional right-hand side operand for unary operators."""
