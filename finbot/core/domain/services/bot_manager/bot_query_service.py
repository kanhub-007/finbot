"""BotQueryService — read-only queries delegated to the state repository.

Extracted from BotManager so MCP history tools and Telegram /history have
a focused, dependency-free query surface. All methods are pure delegation
to the repository (CQRS-lite reads).
"""

from __future__ import annotations

from finbot.core.domain.dto.run_counts import RunCounts
from finbot.core.domain.entities.audit_log_entry import AuditLogEntry
from finbot.core.domain.entities.bot_run import BotRun
from finbot.core.domain.entities.fill_record import FillRecord
from finbot.core.domain.entities.order_response_record import (
    OrderResponseRecord,
)
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.core.domain.entities.risk_event_record import RiskEventRecord
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)


class BotQueryService:
    """Read-only queries over bot run history, signals, orders, fills."""

    def __init__(self, repo: BotStateRepository) -> None:
        self._repo = repo

    def get_bot_run(self, run_id: str) -> BotRun | None:
        """Return a single bot run by ID, or None."""
        return self._repo.get_bot_run(run_id)

    def list_bot_runs(
        self, limit: int = 20, mode_filter: str | None = None
    ) -> list[BotRun]:
        """Return recent bot runs ordered by most recent first."""
        return self._repo.list_bot_runs(limit=limit, mode_filter=mode_filter)

    def get_signals_for_run(self, run_id: str) -> list[ProcessedSignal]:
        """Return all signals for a specific bot run."""
        return self._repo.get_signals_for_run(run_id)

    def get_orders_for_run(self, run_id: str) -> list[OrderResponseRecord]:
        """Return all order responses for a specific bot run."""
        return self._repo.get_orders_for_run(run_id)

    def get_fills_for_run(self, run_id: str) -> list[FillRecord]:
        """Return all fills for a specific bot run."""
        return self._repo.get_fills_for_run(run_id)

    def get_run_counts(self, run_ids: list[str]) -> dict[str, RunCounts]:
        """Return signal/order/fill counts for many runs in one batch."""
        return self._repo.get_run_counts(run_ids)

    def get_risk_events_for_run(self, run_id: str) -> list[RiskEventRecord]:
        """Return all risk events for a specific bot run."""
        return self._repo.get_risk_events_for_run(run_id)

    def get_audit_log(
        self, limit: int = 50, event_type: str | None = None
    ) -> list[AuditLogEntry]:
        """Return recent audit log entries."""
        return self._repo.get_audit_log(limit=limit, event_type=event_type)
