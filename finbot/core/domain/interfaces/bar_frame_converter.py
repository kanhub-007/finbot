"""Bar frame converter interface."""

from abc import ABC, abstractmethod


class BarFrameConverter(ABC):
    @abstractmethod
    def bars_to_frame(self, bars): ...
    @abstractmethod
    def frame_to_bars(self, frame): ...
