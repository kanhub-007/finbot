"""CallbackData — value object for parsing Telegram callback_data strings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CallbackData:
    """Parsed representation of a Telegram inline-keyboard callback.

    Callback data uses colon-separated format: prefix:action:value[:subvalue].
    Examples: run:a1:strat:0, panic:cancel:BTC, panic:exec:BTC:both.
    """

    raw: str
    parts: tuple[str, ...]

    @classmethod
    def parse(cls, raw: str) -> CallbackData:
        """Parse a raw callback_data string into a CallbackData."""
        return cls(raw=raw, parts=tuple(raw.split(":")))

    @property
    def prefix(self) -> str:
        """First segment, e.g. 'run', 'panic', '/status'."""
        return self.parts[0] if self.parts else ""

    def has_prefix(self, prefix: str) -> bool:
        """Check if the first segment matches a given prefix."""
        return len(self.parts) >= 1 and self.parts[0] == prefix

    @property
    def action(self) -> str:
        """Second segment, e.g. 'strat', 'cancel', 'exec'."""
        return self.parts[1] if len(self.parts) > 1 else ""

    @property
    def value(self) -> str:
        """Third segment, e.g. '0', 'BTC', 'yes'."""
        return self.parts[2] if len(self.parts) > 2 else ""

    @property
    def subvalue(self) -> str:
        """Fourth segment, used by panic:exec:sym:action."""
        return self.parts[3] if len(self.parts) > 3 else ""

    @property
    def segment_count(self) -> int:
        """Number of colon-separated segments."""
        return len(self.parts)
