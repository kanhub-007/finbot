"""Tests for the pandas BarFrameConverter — hot-path append optimisation."""

import pandas as pd

from finbot.infrastructure.strategy.pandas_bar_frame_converter import (
    PandasBarFrameConverter,
)


def _sample_frame() -> pd.DataFrame:
    bars = [
        {
            "timestamp": 1000,
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 10,
        },
        {
            "timestamp": 2000,
            "open": 1.5,
            "high": 2.5,
            "low": 1.0,
            "close": 2.0,
            "volume": 20,
        },
    ]
    return PandasBarFrameConverter().bars_to_frame(bars)


def test_append_bar_adds_one_row_without_full_rebuild() -> None:
    """P1: append_bar must extend the frame, not rebuild it from bars."""
    converter = PandasBarFrameConverter()
    frame = _sample_frame()
    original_row_count = len(frame)

    new_bar = {
        "timestamp": 3000,
        "open": 2.0,
        "high": 3.0,
        "low": 1.5,
        "close": 2.5,
        "volume": 30,
    }
    result = (
        converter.append_bar(frame, original_frame=frame, bar=new_bar)
        if False
        else converter.append_bar(frame, new_bar)
    )

    assert len(result) == original_row_count + 1
    # The original frame object must be untouched (append returns a new frame).
    assert len(frame) == original_row_count


def test_append_bar_uses_concat_not_rebuild() -> None:
    """append_bar must not delegate to bars_to_frame (the O(n) rebuild path)."""
    calls = {"bars_to_frame": 0}
    converter = PandasBarFrameConverter()
    original_bars_to_frame = converter.bars_to_frame

    def counting_bars_to_frame(bars):
        calls["bars_to_frame"] += 1
        return original_bars_to_frame(bars)

    converter.bars_to_frame = counting_bars_to_frame
    frame = _sample_frame()
    converter.append_bar(frame, {"timestamp": 3000, "close": 2.5})

    assert calls["bars_to_frame"] == 0, "append_bar must not rebuild via bars_to_frame"
