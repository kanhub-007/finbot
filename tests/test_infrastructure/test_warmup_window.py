"""Tests for WarmupWindow domain service."""

from finbot.core.domain.services.warmup_window import WarmupWindow


class TestWarmupWindowBasics:
    def test_empty_window_is_not_ready(self) -> None:
        w = WarmupWindow(min_bars=3)
        assert not w.is_ready()
        assert w.count == 0

    def test_not_ready_when_below_min(self) -> None:
        w = WarmupWindow(min_bars=3)
        w.append({"timestamp": 1})
        w.append({"timestamp": 2})
        assert not w.is_ready()
        assert w.count == 2

    def test_ready_when_min_reached(self) -> None:
        w = WarmupWindow(min_bars=2)
        w.append({"timestamp": 1})
        w.append({"timestamp": 2})
        w.append({"timestamp": 3})
        assert w.is_ready()
        assert w.count == 3

    def test_constructor_rejects_invalid_sizes(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="max_length"):
            WarmupWindow(max_length=10, min_bars=20)


class TestWarmupWindowDeduplication:
    def test_same_timestamp_overwrites(self) -> None:
        w = WarmupWindow(min_bars=2)
        w.append({"timestamp": 1, "close": 100})
        w.append({"timestamp": 1, "close": 200})
        assert w.count == 1
        bars = w.bars
        assert bars[0]["close"] == 200


class TestWarmupWindowSorting:
    def test_bars_returned_in_ascending_order(self) -> None:
        w = WarmupWindow(min_bars=2)
        w.append({"timestamp": 3})
        w.append({"timestamp": 1})
        w.append({"timestamp": 2})
        bars = w.bars
        assert [b["timestamp"] for b in bars] == [1, 2, 3]

    def test_oldest_bars_evicted_on_overflow(self) -> None:
        w = WarmupWindow(max_length=3, min_bars=2)
        for i in range(5):
            w.append({"timestamp": i})
        assert w.count == 3
        timestamps = [b["timestamp"] for b in w.bars]
        assert timestamps == [2, 3, 4]


class TestWarmupWindowGapDetection:
    def test_regular_intervals_no_gap(self) -> None:
        w = WarmupWindow(min_bars=3)
        # 3600-second intervals
        for h in range(5):
            w.append({"timestamp": h * 3600})
        assert w.is_ready()
        assert not w.has_gap

    def test_large_jump_detected_as_gap(self) -> None:
        w = WarmupWindow(min_bars=3)
        w.append({"timestamp": 0})
        w.append({"timestamp": 3600})
        w.append({"timestamp": 7200})  # regular so far
        w.append({"timestamp": 7200 + 7200})  # double gap → detected
        assert w.has_gap
        assert not w.is_ready()

    def test_gap_recovery_after_eviction(self) -> None:
        w = WarmupWindow(max_length=4, min_bars=3)
        # Fill with 5 bars: bar 0 has a gap with bar 1
        w.append({"timestamp": 0})
        w.append({"timestamp": 7200})  # gap!
        w.append({"timestamp": 7200 + 3600})
        w.append({"timestamp": 7200 + 7200})
        assert w.has_gap
        # Add a bar that pushes out the gap (bar 0 gets evicted)
        w.append({"timestamp": 7200 + 10800})
        # Now all remaining bars (1-4) are consecutive
        assert not w.has_gap
        assert w.is_ready()


class TestWarmupWindowStringTimestamps:
    def test_iso_timestamps(self) -> None:
        w = WarmupWindow(min_bars=2)
        w.append({"timestamp": "2025-01-01T09:00:00"})
        w.append({"timestamp": "2025-01-01T10:00:00"})
        assert w.is_ready()
        assert w.count == 2

    def test_space_separated_timestamps(self) -> None:
        w = WarmupWindow(min_bars=2)
        w.append({"timestamp": "2025-01-01 09:00:00"})
        w.append({"timestamp": "2025-01-01 10:00:00"})
        assert w.is_ready()

    def test_unparseable_timestamp_ignored(self) -> None:
        w = WarmupWindow(min_bars=2)
        w.append({"timestamp": "not-a-time"})
        w.append({"timestamp": "2025-01-01T10:00:00"})
        assert w.count == 1
