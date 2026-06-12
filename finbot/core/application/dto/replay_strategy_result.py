"""Result DTO for a strategy replay run."""

from dataclasses import dataclass, field

from finbot.core.application.dto.signal_event import SignalEvent


@dataclass(frozen=True)
class ReplayStrategyResult:
    """Output from a replay run."""

    status: str
    signal_count: int = 0
    signals: list[SignalEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
