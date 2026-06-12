"""Signal event DTO — a single signal produced during replay or live run.

Every field is optional except ``action`` so the DTO can evolve without
breaking existing test callers.
"""

from dataclasses import dataclass

from finbot.core.domain.entities.signal_action import SignalAction


@dataclass(frozen=True)
class SignalEvent:
    """A strategy signal captured during replay or live execution.

    Correlation fields link the signal to its originating bot run,
    strategy, bar, and downstream order intent.
    """

    action: SignalAction

    # -- trade signal data --------------------------------------------------
    symbol: str = ""
    bar_index: int = 0
    close: float = 0.0
    stop_price: float | None = None
    target_price: float | None = None
    confidence: float = 0.0
    warmup_ready: bool = True

    # -- correlation fields -------------------------------------------------
    bot_run_id: str = ""
    strategy_name: str = ""
    strategy_hash: str = ""
    interval: str = ""
    candle_timestamp: str = ""
    signal_key: str = ""
    order_intent_id: str = ""
    cloid: str | None = None
    mode: str = ""
