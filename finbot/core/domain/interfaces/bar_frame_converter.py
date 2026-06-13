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

    @abstractmethod
    def is_empty(self, frame: Any) -> bool:
        """Return True if the frame has no rows or columns."""
