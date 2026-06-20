"""InformativeBarCache domain interface (MTF support)."""

from abc import ABC, abstractmethod
from typing import Any


class InformativeBarCache(ABC):
    """Stores the latest bar per informative timeframe alias.

    The runtime updates this cache from informative websocket streams
    and merges cached values into the primary bar before indicator
    calculation.  Implementations must be thread-safe for the main-thread
    dispatch model used by ``BotEventLoop``.
    """

    @abstractmethod
    def update(self, alias: str, bar: dict[str, Any]) -> None:
        """Store the latest bar for *alias*."""

    @abstractmethod
    def get(self, alias: str) -> dict[str, Any] | None:
        """Return the cached bar for *alias*, or ``None``."""

    @abstractmethod
    def is_empty(self, alias: str) -> bool:
        """Return ``True`` when no bar has been cached for *alias*."""

    @abstractmethod
    def merge_into(self, primary: dict[str, Any], *, alias: str) -> dict[str, Any]:
        """Return a new dict with *primary* keys plus *alias*-prefixed
        keys from the cached bar."""

    def merge_all(
        self, primary: dict[str, Any], *, aliases: list[str]
    ) -> dict[str, Any]:
        """Like :meth:`merge_into` but for all given *aliases*."""
        merged = dict(primary)
        for alias in aliases:
            merged = self.merge_into(merged, alias=alias)
        return merged
