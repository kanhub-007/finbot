"""Warmup window — sliding buffer of recent closed bars.

Pure domain service with no I/O dependencies. Manages a capped,
sorted, deduplicated bar buffer and declares readiness when the
minimum number of bars has been accumulated with no gaps.
"""

from __future__ import annotations

import bisect
import statistics
from datetime import UTC, datetime
from typing import Any


class WarmupWindow:
    """Sliding window of the most recent closed bars.

    Bars are sorted by timestamp, deduplicated, and capped to
    ``max_length``. The window detects interval gaps and reports
    whether enough consecutive bars exist to begin strategy evaluation.

    Parameters
    ----------
    max_length:
        Maximum number of bars to retain. Oldest bars are evicted first.
    min_bars:
        Number of consecutive, gap-free bars required before
        ``is_ready()`` returns True.
    """

    def __init__(self, max_length: int = 500, min_bars: int = 20) -> None:
        if max_length < min_bars:
            raise ValueError(
                f"max_length ({max_length}) must be >= min_bars ({min_bars})"
            )
        self._max_length = max_length
        self._min_bars = min_bars
        self._bars: dict[int, dict[str, Any]] = {}
        self._sorted_ts: list[int] = []
        self._has_gap = False
        # Cached gap analysis — recomputed only when the window content changes
        # (append/evict), not on every is_ready()/has_gap read on the hot path.
        self._gap_dirty = True

    # -- public API --------------------------------------------------------

    def append(self, bar: dict[str, Any]) -> None:
        """Insert a closed bar, deduplicating by timestamp."""
        ts = self._normalise_timestamp(bar)
        if ts is None:
            return
        if ts not in self._bars:
            bisect.insort(self._sorted_ts, ts)
        self._bars[ts] = bar
        self._gap_dirty = True
        self._evict_oldest()
        self._detect_gap_if_dirty()

    def is_ready(self) -> bool:
        """True when at least ``min_bars`` consecutive bars exist."""
        self._detect_gap_if_dirty()
        return len(self._bars) >= self._min_bars and not self._has_gap

    @property
    def bars(self) -> list[dict[str, Any]]:
        """Return bars in ascending timestamp order."""
        return [self._bars[k] for k in self._sorted_ts]

    @property
    def latest_bar(self) -> dict[str, Any]:
        """Return the most recent bar (O(1)); empty dict if none."""
        if not self._sorted_ts:
            return {}
        return self._bars[self._sorted_ts[-1]]

    @property
    def count(self) -> int:
        """Number of bars currently stored."""
        return len(self._bars)

    @property
    def max_length(self) -> int:
        return self._max_length

    @property
    def min_bars(self) -> int:
        return self._min_bars

    @property
    def has_gap(self) -> bool:
        """True when a non-consecutive interval was detected."""
        self._detect_gap_if_dirty()
        return self._has_gap

    # -- internal -----------------------------------------------------------

    @staticmethod
    def _normalise_timestamp(bar: dict[str, Any]) -> int | None:
        raw = bar.get("timestamp")
        if raw is None:
            return None
        try:
            if isinstance(raw, (int, float)):
                return int(raw)
            if isinstance(raw, datetime):
                # Naive datetimes are assumed UTC (bar timestamps are always
                # UTC in the exchange feed).
                dt = raw if raw.tzinfo else raw.replace(tzinfo=UTC)
                return int(dt.timestamp())
            # string — try ISO, then epoch int/float.
            # All bar timestamps are UTC; naive-parsed strings are assumed UTC.
            s = str(raw)
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(s, fmt).replace(tzinfo=UTC)
                    return int(dt.timestamp())
                except ValueError:
                    continue
            return int(float(s))
        except (ValueError, TypeError):
            return None

    def _evict_oldest(self) -> None:
        evicted = False
        while len(self._bars) > self._max_length:
            oldest = self._sorted_ts[0]
            del self._bars[oldest]
            self._sorted_ts.pop(0)
            evicted = True
        if evicted:
            self._gap_dirty = True

    def _detect_gap_if_dirty(self) -> None:
        """Recompute the gap flag only when the window changed since last call."""
        if self._gap_dirty:
            self._detect_gap()
            self._gap_dirty = False

    def _detect_gap(self) -> None:
        """Scan sorted timestamps; flag irregular intervals as gaps.

        Uses the **median interval** across all stored bars as the
        expected cadence.  Any interval that deviates 50% or more from
        the median is treated as a gap.
        """
        n = len(self._sorted_ts)
        if n < 2:
            self._has_gap = False
            return
        intervals = [self._sorted_ts[i + 1] - self._sorted_ts[i] for i in range(n - 1)]
        expected = _median(intervals)
        if expected <= 0:
            self._has_gap = False
            return
        threshold = expected * 0.5
        for di in intervals:
            if abs(di - expected) >= threshold:
                self._has_gap = True
                return
        self._has_gap = False


def _median(values: list[int]) -> int:
    """Return the median of a non-empty list of integers."""
    return int(statistics.median(values))
