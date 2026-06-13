"""Test for the warmup gap-detection cache (P6 optimisation)."""

from finbot.core.domain.services.warmup_window import WarmupWindow


def test_gap_analysis_is_cached_across_reads(monkeypatch) -> None:
    """Multiple has_gap / is_ready reads never recompute the median."""
    w = WarmupWindow(min_bars=2)
    w.append({"timestamp": 1000, "close": 1.0})
    w.append({"timestamp": 2000, "close": 2.0})
    w.append({"timestamp": 3000, "close": 3.0})

    calls = {"n": 0}
    real_detect = w._detect_gap

    def counting_detect():
        calls["n"] += 1
        return real_detect()

    w._detect_gap = counting_detect

    # Several reads without an intervening append.
    _ = w.has_gap
    _ = w.is_ready()
    _ = w.has_gap

    assert calls["n"] == 0, "reads must use the cache, not recompute the median"


def test_gap_analysis_recomputes_after_append() -> None:
    """A new append dirties the cache so the next read recomputes."""
    w = WarmupWindow(min_bars=2)
    w.append({"timestamp": 1000, "close": 1.0})
    w.append({"timestamp": 2000, "close": 2.0})
    _ = w.has_gap  # populates cache

    # Append a gappy bar.
    w.append({"timestamp": 99999, "close": 9.0})
    assert w.has_gap is True
