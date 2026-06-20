"""InformativeBarCache — holds the latest bar per informative timeframe.

Used by the live trading runtime to merge higher-timeframe context into
each primary-timeframe bar before indicator calculation (MTF support).
"""

from __future__ import annotations

from typing import Any

from finbot.core.domain.interfaces.informative_bar_cache import (
    InformativeBarCache as InformativeBarCacheInterface,
)


class InformativeBarCache(InformativeBarCacheInterface):
    """Dict-backed cache of the latest bar per informative timeframe alias.

    Each alias (e.g. ``"h1"``) maps to the most recent bar dict received
    from that timeframe's websocket stream.  The runtime calls ``update()``
    from ``process_informative_candle()`` and ``merge_into()`` before
    indicator calculation.

    Thread-safe for the use case where the event loop dispatches
    informative candles on the main thread (no concurrent access).
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}

    def update(self, alias: str, bar: dict[str, Any]) -> None:
        """Store the latest bar for *alias*."""
        self._cache[alias] = dict(bar)

    def get(self, alias: str) -> dict[str, Any] | None:
        """Return the cached bar for *alias*, or ``None``."""
        return self._cache.get(alias)

    def is_empty(self, alias: str) -> bool:
        """Return ``True`` when no bar has been cached for *alias*."""
        return alias not in self._cache

    def merge_into(self, primary: dict[str, Any], *, alias: str) -> dict[str, Any]:
        """Return a new dict with *primary* keys plus *alias*-prefixed
        keys from the cached bar.

        Does not mutate *primary*.  When no bar is cached for *alias*,
        returns *primary* unchanged.
        """
        bar = self._cache.get(alias)
        if bar is None:
            return primary
        merged = dict(primary)
        for key, value in bar.items():
            merged[f"{alias}_{key}"] = value
        return merged

    def merge_all(
        self, primary: dict[str, Any], *, aliases: list[str]
    ) -> dict[str, Any]:
        """Like :meth:`merge_into` but for all given *aliases*."""
        merged = dict(primary)
        for alias in aliases:
            bar = self._cache.get(alias)
            if bar is None:
                continue
            for key, value in bar.items():
                merged[f"{alias}_{key}"] = value
        return merged
