"""Bot state repository interface."""

from abc import ABC, abstractmethod

from finbot.core.domain.entities.audit_log_entry import AuditLogEntry
from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_response_record import (
    OrderResponseRecord,
)
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.core.domain.entities.reconciliation_record import (
    ReconciliationRecord,
)
from finbot.core.domain.entities.risk_event_record import RiskEventRecord
from finbot.core.domain.entities.strategy_snapshot import StrategySnapshot


class BotStateRepository(ABC):
    """Persists bot signals, intents, orders, fills, and audit events."""

    # -- bot run lifecycle --------------------------------------------------

    @abstractmethod
    def create_bot_run(self, bot_run: BotRun) -> None:
        """Record a new bot execution session."""

    @abstractmethod
    def end_bot_run(self, run_id: str) -> None:
        """Mark a bot run as completed."""

    # -- strategy snapshot --------------------------------------------------

    @abstractmethod
    def store_strategy_snapshot(self, snapshot: StrategySnapshot) -> None:
        """Persist a frozen copy of the strategy YAML."""

    # -- signals ------------------------------------------------------------

    @abstractmethod
    def has_processed_signal(self, signal_key: str) -> bool:
        """Return whether a signal key has already been processed."""

    @abstractmethod
    def mark_signal_processed(self, signal: ProcessedSignal) -> None:
        """Mark a signal key as processed to prevent duplicate orders."""

    # -- order intents & responses ------------------------------------------

    @abstractmethod
    def record_order_intent(self, intent: OrderIntent) -> str:
        """Persist an order intent before exchange submission."""

    @abstractmethod
    def record_order_response(self, response: OrderResponseRecord) -> None:
        """Persist the exchange response for an order intent."""

    # -- fills --------------------------------------------------------------

    @abstractmethod
    def record_fill(self, fill: FillRecord) -> None:
        """Persist a trade fill from the exchange."""

    # -- reconciliation -----------------------------------------------------

    @abstractmethod
    def record_reconciliation(self, rec: ReconciliationRecord) -> None:
        """Persist a reconciliation result."""

    # -- risk events --------------------------------------------------------

    @abstractmethod
    def record_risk_event(self, event: RiskEventRecord) -> None:
        """Persist a risk gate decision."""

    # -- audit log ----------------------------------------------------------

    @abstractmethod
    def append_audit_log(self, entry: AuditLogEntry) -> None:
        """Append an entry to the append-only audit log."""

    # -- status queries (CQRS-lite reads) -----------------------------------

    @abstractmethod
    def get_latest_bot_run(self) -> BotRun | None:
        """Return the most recently created bot run, or None."""

    @abstractmethod
    def get_last_signal(self) -> ProcessedSignal | None:
        """Return the most recently processed signal, or None."""

    @abstractmethod
    def get_last_order_response(
        self,
    ) -> OrderResponseRecord | None:
        """Return the most recent order response, or None."""

    @abstractmethod
    def count_signals(self) -> int:
        """Total number of processed signals across all runs."""

    @abstractmethod
    def count_orders(self) -> int:
        """Total number of recorded order intents."""

    @abstractmethod
    def count_fills(self) -> int:
        """Total number of recorded fills."""
