"""Bot state repository interface."""

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

from finbot.core.domain.dto.run_counts import RunCounts
from finbot.core.domain.entities.audit_log_entry import AuditLogEntry
from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_lifecycle import OrderLifecycle
from finbot.core.domain.entities.order_response_record import (
    OrderResponseRecord,
)
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.core.domain.entities.reconciliation_record import (
    ReconciliationRecord,
)
from finbot.core.domain.entities.risk_event_record import RiskEventRecord
from finbot.core.domain.entities.strategy_snapshot import StrategySnapshot
from finbot.core.domain.entities.trade import Trade


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

    # -- fill idempotency ----------------------------------------------------

    @abstractmethod
    def has_fill(self, fill_id: str) -> bool:
        """Return True if *fill_id* has already been recorded."""

    # -- run history queries -------------------------------------------------

    @abstractmethod
    def get_bot_run(self, run_id: str) -> BotRun | None:
        """Return a single bot run by its run_id, or None."""

    @abstractmethod
    def list_bot_runs(
        self, limit: int = 20, mode_filter: str | None = None
    ) -> list[BotRun]:
        """Return recent bot runs ordered by started_at DESC."""

    @abstractmethod
    def get_signals_for_run(self, run_id: str) -> list[ProcessedSignal]:
        """Return all signals for a specific bot run."""

    @abstractmethod
    def get_orders_for_run(self, run_id: str) -> list[OrderResponseRecord]:
        """Return all order responses for a specific bot run."""

    @abstractmethod
    def get_run_counts(self, run_ids: list[str]) -> dict[str, RunCounts]:
        """Return signal/order/fill counts for each run in ``run_ids``.

        Runs with no rows (or not present) map to ``RunCounts(0, 0, 0)``.
        Implementations should satisfy this with at most one query per
        table (GROUP BY bot_run_id) instead of N+1 per-run fetches.
        """

    @abstractmethod
    def get_fills_for_run(self, run_id: str) -> list[FillRecord]:
        """Return all fills for a specific bot run."""

    @abstractmethod
    def get_risk_events_for_run(self, run_id: str) -> list[RiskEventRecord]:
        """Return all risk events for a specific bot run."""

    @abstractmethod
    def get_audit_log(
        self, limit: int = 50, event_type: str | None = None
    ) -> list[AuditLogEntry]:
        """Return recent audit log entries."""

    # -- order lifecycle -----------------------------------------------------

    @abstractmethod
    def get_order_lifecycle(self, order_id: str) -> OrderLifecycle | None:
        """Return the lifecycle for *order_id*, or None."""

    @abstractmethod
    def save_order_lifecycle(self, lifecycle: OrderLifecycle) -> None:
        """Persist an order lifecycle state update."""

    # -- trades ---------------------------------------------------------------

    @abstractmethod
    def open_trade(self, trade: Trade) -> None:
        """Persist a new open trade record."""

    @abstractmethod
    def update_trade(self, trade: Trade) -> None:
        """Replace an existing trade row with the updated frozen entity."""

    @abstractmethod
    def get_open_trade(self, symbol: str) -> Trade | None:
        """Return the currently open Trade for *symbol*, or None."""

    @abstractmethod
    def list_open_trades(self) -> list[Trade]:
        """Return all open trades."""

    @abstractmethod
    def list_closed_trades(self, *, bot_run_id: str | None = None) -> list[Trade]:
        """Return closed trades, optionally filtered by bot run."""

    @abstractmethod
    def realized_loss_on(self, day: date) -> Decimal:
        """Sum of absolute realized losses for trades closed on *day*."""
