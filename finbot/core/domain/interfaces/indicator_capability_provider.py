"""IndicatorCapabilityProvider interface for strategy/indicator metadata."""

from abc import ABC, abstractmethod


class IndicatorCapabilityProvider(ABC):
    """Expose indicator capabilities without coupling callers to calculators."""

    @abstractmethod
    def resolve(self, indicator_type: str, period: int | None) -> str | None:
        """Resolve an indicator type and optional period to a concrete column."""

    @abstractmethod
    def requires_period(self, indicator_type: str) -> bool:
        """Return True when an indicator type requires a period."""

    @abstractmethod
    def accepts_period(self, indicator_type: str) -> bool:
        """Return True when an indicator type accepts a period parameter."""

    @abstractmethod
    def supports_concrete(self, name: str) -> bool:
        """Return True when a concrete indicator column is supported."""

    @abstractmethod
    def supported_concrete_names(self) -> list[str]:
        """Return all supported concrete indicator columns."""

    @abstractmethod
    def as_dict(self) -> dict:
        """Return a JSON-serializable capabilities payload."""
