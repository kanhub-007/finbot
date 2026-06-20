"""Transactional helper — runs a callable inside a repo transaction if available.

Shared by use cases that need optional transaction wrapping without
duplicating the ``getattr(repo, "transaction", None)`` pattern.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)

T = TypeVar("T")


def transactional[T](
    repo: BotStateRepository,
    fn: Callable[[], T],
) -> T:
    """Run *fn* inside a repo transaction if the repo supports one.

    Falls back to direct execution for in-memory repos that don't expose
    ``transaction`` (they have no fsync cost to avoid).
    """
    tx = getattr(repo, "transaction", None)
    if tx is None:
        return fn()
    with tx():
        return fn()
