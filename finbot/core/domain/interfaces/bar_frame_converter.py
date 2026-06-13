"""Bar frame converter interface."""

from abc import ABC, abstractmethod
from typing import Any


class BarFrameConverter(ABC):
    """Convert between raw bar dicts and frame-like types (e.g. DataFrame).

    Decouples the application layer from the concrete frame library.
    """

    @abstractmethod
    def bars_to_frame(self, bars: list[dict]) -> Any:
        """Convert a list of OHLCV bar dicts to a frame object."""

    @abstractmethod
    def frame_to_bars(self, frame: Any) -> list[dict]:
        """Convert a frame object back to a list of dicts."""

    @abstractmethod
    def latest_bar(self, frame: Any) -> dict:
        """Return the last row of the frame as a dict."""

    def append_bar(self, frame: Any, bar: dict) -> Any:
        """Return a frame with one bar appended.

        Default implementation rebuilds from ``frame_to_bars`` + the new bar.
        Implementations backed by an in-memory frame should override this to
        avoid reallocating the whole frame on the candle hot path.
        """
        bars = self.frame_to_bars(frame)
        bars.append(bar)
        return self.bars_to_frame(bars)

    @abstractmethod
    def is_empty(self, frame: Any) -> bool:
        """Return True if the frame has no rows or columns."""
