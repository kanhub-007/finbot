"""In-memory bot state repository for early dry-run development."""

from typing import Any
from uuid import uuid4

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
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)


class InMemoryBotStateRepository(BotStateRepository):
    """Stores bot state in process memory for tests and dry-run skeletons."""

    def __init__(self) -> None:
        self._responses: dict[str, dict[str, Any]] = {}
        self._processed: set[str] = set()
        self._processed_signals: list[ProcessedSignal] = []
        self._bot_runs: list[BotRun] = []
        self._snapshots: list[StrategySnapshot] = []
        self._fills: list[FillRecord] = []
        self._reconciliations: list[ReconciliationRecord] = []
        self._risk_events: list[RiskEventRecord] = []
        self._audit_log: list[AuditLogEntry] = []

    # -- bot run lifecycle --------------------------------------------------

    def create_bot_run(self, bot_run: BotRun) -> None:
        self._bot_runs.append(bot_run)

    def end_bot_run(self, run_id: str) -> None:
        for run in self._bot_runs:
            if run.run_id == run_id:
                object.__setattr__(run, "ended_at", run.started_at)
                return

    # -- strategy snapshot --------------------------------------------------

    def store_strategy_snapshot(self, snapshot: StrategySnapshot) -> None:
        self._snapshots.append(snapshot)

    # -- signals ------------------------------------------------------------

    def has_processed_signal(self, signal_key: str) -> bool:
        return signal_key in self._processed

    def mark_signal_processed(self, signal: ProcessedSignal) -> None:
        self._processed.add(signal.signal_key)
        self._processed_signals.append(signal)

    # -- order intents & responses ------------------------------------------

    def record_order_intent(self, intent: OrderIntent) -> str:
        intent_id = str(uuid4())
        self._responses[intent_id] = {"intent": intent}
        return intent_id

    def record_order_response(self, response: OrderResponseRecord) -> None:
        if response.intent_id not in self._responses:
            raise KeyError(
                f"Unknown intent_id {response.intent_id}: "
                f"record_order_intent must be called first"
            )
        self._responses[response.intent_id]["response"] = response

    # -- fills --------------------------------------------------------------

    def record_fill(self, fill: FillRecord) -> None:
        self._fills.append(fill)

    # -- reconciliation -----------------------------------------------------

    def record_reconciliation(self, rec: ReconciliationRecord) -> None:
        self._reconciliations.append(rec)

    # -- risk events --------------------------------------------------------

    def record_risk_event(self, event: RiskEventRecord) -> None:
        self._risk_events.append(event)

    # -- audit log ----------------------------------------------------------

    def append_audit_log(self, entry: AuditLogEntry) -> None:
        self._audit_log.append(entry)

    # -- status queries ----------------------------------------------------

    def get_latest_bot_run(self) -> BotRun | None:
        return self._bot_runs[-1] if self._bot_runs else None

    def get_last_signal(self) -> ProcessedSignal | None:
        return self._processed_signals[-1] if self._processed_signals else None

    def get_last_order_response(
        self,
    ) -> OrderResponseRecord | None:
        for rid in reversed(list(self._responses.keys())):
            resp = self._responses[rid].get("response")
            if resp is not None:
                return resp
        return None

    def count_signals(self) -> int:
        return len(self._processed)

    def count_orders(self) -> int:
        return len(self._responses)

    def count_fills(self) -> int:
        return len(self._fills)
