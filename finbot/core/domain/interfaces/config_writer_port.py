"""ConfigWriterPort — persists runtime config changes to durable storage.

Implementations write ``RuntimeBotConfig`` values back to ``.env`` (or another
durable store) so runtime changes survive restarts. Domain-pure interface.
"""

from __future__ import annotations

from typing import Protocol


class ConfigWriterPort(Protocol):
    """Write runtime config key/value pairs to durable storage."""

    def write(self, key: str, value: str) -> None:
        """Persist a single config key/value pair.

        Args:
            key: Short config key (e.g. "max_position").
            value: The value as a string.
        """
        ...
