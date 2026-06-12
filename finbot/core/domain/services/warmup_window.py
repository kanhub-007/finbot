"""Warmup window — sliding buffer of recent closed bars.

Pure domain service with no I/O dependencies. Manages a capped,
sorted, deduplicated bar buffer and declares readiness when the
minimum number of bars has been accumulated with no gaps.
"""

from __future__ import annotations

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
        self._has_gap = False

    # -- public API --------------------------------------------------------

    def append(self, bar: dict[str, Any]) -> None:
        """Insert a closed bar, deduplicating by timestamp."""
        ts = self._normalise_timestamp(bar)
        if ts is None:
            return
        self._bars[ts] = bar
        self._evict_oldest()
        self._detect_gap()

    def is_ready(self) -> bool:
        """True when at least ``min_bars`` consecutive bars exist."""
        return len(self._bars) >= self._min_bars and not self._has_gap

    @property
    def bars(self) -> list[dict[str, Any]]:
        """Return bars in ascending timestamp order."""
        return [self._bars[k] for k in sorted(self._bars)]

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
                return int(raw.timestamp())
            # string — try ISO, then epoch int/float
            s = str(raw)
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(s, fmt)
                    return int(dt.replace(tzinfo=UTC).timestamp())
                except ValueError:
                    continue
            return int(float(s))
        except (ValueError, TypeError):
            return None

    def _evict_oldest(self) -> None:
        while len(self._bars) > self._max_length:
            oldest = min(self._bars)
            del self._bars[oldest]

    def _detect_gap(self) -> None:
        if len(self._bars) < 2:
            return
        timestamps = list(self._bars.keys())
        d0 = timestamps[1] - timestamps[0]
        if d0 <= 0:
            return
        for i in range(1, len(timestamps) - 1):
            di = timestamps[i + 1] - timestamps[i]
            if abs(di - d0) >= (d0 * 0.5):  # ≥50% deviation = gap
                self._has_gap = True
                return
        self._has_gap = False
