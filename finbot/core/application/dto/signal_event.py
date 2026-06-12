"""Signal event DTO — a single signal produced during replay."""

from dataclasses import dataclass

from finbot.core.domain.entities.signal_action import SignalAction


@dataclass(frozen=True)
class SignalEvent:
    """A strategy signal captured during replay."""

    action: SignalAction
    symbol: str = ""
    bar_index: int = 0
    warmup_ready: bool = True
    close: float = 0.0
    stop_price: float | None = None
    target_price: float | None = None
    confidence: float = 0.0
