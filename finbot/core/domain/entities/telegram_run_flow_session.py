"""TelegramRunFlowSession — stores /run guided-flow state server-side."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from finbot.core.domain.entities.manual_order_draft import ManualOrderDraft


@dataclass
class TelegramRunFlowSession:
    """Server-side session for the multi-step /run guided flow.

    Stores accumulated selections (strategy, symbol, interval, mode)
    so callback_data can stay under Telegram's 64-byte limit.
    The session_id is a short string used in callback payloads.
    """

    session_id: str
    chat_id: int
    message_id: int
    strategy_path: str | None = None
    symbol: str | None = None
    interval: str | None = None
    mode: str | None = None
    #: Risk percentage per trade (e.g. 3 for 3%). Set during /run risk step.
    risk_pct: int = 3
    #: Leverage multiplier (e.g. 5 for 5x). Set during /run risk step.
    leverage: int = 5
    #: Informative intervals for MTF strategies (stored for risk→mode flow).
    _informative_intervals: list[str] = field(default_factory=list)
    #: Typed stash for manual-order params awaiting confirmation (M9).
    #: Replaces the prior ``interval = "long|0.1|sl|tp"`` serialised hack.
    manual_order_draft: ManualOrderDraft | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30)
    )

    @property
    def is_expired(self, now: datetime | None = None) -> bool:
        """Check if the session has expired."""
        now = now or datetime.now(UTC)
        return now > self.expires_at
