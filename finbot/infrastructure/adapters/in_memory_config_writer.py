"""In-memory ConfigWriter fake — records writes for test assertions."""

from __future__ import annotations


class InMemoryConfigWriter:
    """Records config writes; never touches the filesystem."""

    def __init__(self) -> None:
        self.writes: dict[str, str] = {}

    def write(self, key: str, value: str) -> None:
        """Record the write."""
        self.writes[key] = value
