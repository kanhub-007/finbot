"""Cloid generator interface — deterministic client order ID contract."""

from abc import ABC, abstractmethod


class CloidGenerator(ABC):
    """Generate deterministic client order IDs for idempotent submission."""

    @abstractmethod
    def generate(self, signal_key: str = "", attempt: int = 0) -> str:
        """Return a cloid string.

        Args:
            signal_key: Signal key to seed the cloid for deterministic reuse.
            attempt: Retry attempt number appended as suffix.
        """
