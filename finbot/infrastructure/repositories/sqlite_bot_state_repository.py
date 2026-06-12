"""SQLite bot state repository — persists all bot state to a local SQLite DB."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

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


class SqliteBotStateRepository(BotStateRepository):
    """SQLite-backed bot state persistence.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file (e.g. ``data/finbot.db``).
    """

    def __init__(self, db_path: str = "data/finbot.db") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def close(self) -> None:
        """Close the underlying database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self):
        """Context manager that defers commit until the block exits.

        Usage::

            with repo.transaction():
                repo.record_order_intent(intent)
                repo.mark_signal_processed(signal)

        All writes inside the block are committed atomically when the
        block exits without exception.
        """
        try:
            self._connection.isolation_level = None  # manual txn
            self._connection.execute("BEGIN")
            yield
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        finally:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.isolation_level = ""  # back to autocommit

    # -- bot run lifecycle --------------------------------------------------

    def create_bot_run(self, bot_run: BotRun) -> None:
        self._execute(
            "INSERT OR IGNORE INTO bot_runs "
            "(run_id, strategy_name, strategy_hash, "
            "symbol, interval, mode, started_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                bot_run.run_id,
                bot_run.strategy_name,
                bot_run.strategy_hash,
                bot_run.symbol,
                bot_run.interval,
                bot_run.mode,
                _to_utc_text(bot_run.started_at),
            ),
        )

    def end_bot_run(self, run_id: str) -> None:
        self._execute(
            "UPDATE bot_runs SET ended_at = ? WHERE run_id = ?",
            (_to_utc_text(datetime.now(UTC)), run_id),
        )

    # -- strategy snapshot --------------------------------------------------

    def store_strategy_snapshot(self, snapshot: StrategySnapshot) -> None:
        self._execute(
            "INSERT INTO strategy_snapshots "
            "(snapshot_id, bot_run_id, strategy_hash, full_yaml, created_at) "
            "VALUES (?,?,?,?,?)",
            (
                snapshot.snapshot_id,
                snapshot.bot_run_id,
                snapshot.strategy_hash,
                snapshot.full_yaml,
                _to_utc_text(snapshot.created_at),
            ),
        )

    # -- signals ------------------------------------------------------------

    def has_processed_signal(self, signal_key: str) -> bool:
        row = self._query_one(
            "SELECT 1 FROM processed_signals WHERE signal_key = ?",
            (signal_key,),
        )
        return row is not None

    def mark_signal_processed(self, signal: ProcessedSignal) -> None:
        self._execute(
            "INSERT OR IGNORE INTO processed_signals "
            "(signal_key, bot_run_id, signal_action, bar_timestamp, created_at) "
            "VALUES (?,?,?,?,?)",
            (
                signal.signal_key,
                signal.bot_run_id,
                signal.signal_action,
                signal.bar_timestamp,
                _to_utc_text(signal.created_at),
            ),
        )

    # -- order intents & responses ------------------------------------------

    def record_order_intent(self, intent: OrderIntent) -> str:
        import uuid

        intent_id = uuid.uuid4().hex
        self._execute(
            "INSERT INTO order_intents "
            "(intent_id, signal_key, symbol, side, order_type, size, "
            "price, stop_price, reduce_only, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                intent_id,
                intent.signal_key,
                intent.symbol,
                intent.side.value,
                intent.order_type.value,
                str(intent.size),
                str(intent.limit_price) if intent.limit_price else None,
                str(intent.stop_price) if intent.stop_price else None,
                1 if intent.reduce_only else 0,
                _to_utc_text(datetime.now(UTC)),
            ),
        )
        return intent_id

    def record_order_response(self, response: OrderResponseRecord) -> None:
        self._execute(
            "INSERT INTO order_responses "
            "(response_id, intent_id, bot_run_id, response_json, status, "
            "created_at) VALUES (?,?,?,?,?,?)",
            (
                response.response_id,
                response.intent_id,
                response.bot_run_id,
                response.response_json,
                response.status,
                _to_utc_text(response.created_at),
            ),
        )

    # -- fills --------------------------------------------------------------

    def record_fill(self, fill: FillRecord) -> None:
        self._execute(
            "INSERT INTO fills "
            "(fill_id, bot_run_id, order_id, symbol, side, size, price, "
            "fee, filled_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                fill.fill_id,
                fill.bot_run_id,
                fill.order_id,
                fill.symbol,
                fill.side,
                str(fill.size),
                str(fill.price),
                str(fill.fee),
                _to_utc_text(fill.filled_at),
            ),
        )

    # -- reconciliation -----------------------------------------------------

    def record_reconciliation(self, rec: ReconciliationRecord) -> None:
        self._execute(
            "INSERT INTO reconciliations "
            "(reconciliation_id, bot_run_id, position_matches, "
            "open_orders_match, exchange_state_json, details, reconciled_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                rec.reconciliation_id,
                rec.bot_run_id,
                1 if rec.position_matches else 0,
                1 if rec.open_orders_match else 0,
                rec.exchange_state_json,
                rec.details,
                _to_utc_text(rec.reconciled_at),
            ),
        )

    # -- risk events --------------------------------------------------------

    def record_risk_event(self, event: RiskEventRecord) -> None:
        self._execute(
            "INSERT INTO risk_events "
            "(event_id, bot_run_id, event_type, signal_key, decision, "
            "reason, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                event.event_id,
                event.bot_run_id,
                event.event_type,
                event.signal_key,
                event.decision,
                event.reason,
                _to_utc_text(event.created_at),
            ),
        )

    # -- audit log ----------------------------------------------------------

    def append_audit_log(self, entry: AuditLogEntry) -> None:
        self._execute(
            "INSERT INTO audit_log "
            "(entry_id, bot_run_id, event_type, event_data_json, created_at) "
            "VALUES (?,?,?,?,?)",
            (
                entry.entry_id,
                entry.bot_run_id,
                entry.event_type,
                entry.event_data_json,
                _to_utc_text(entry.created_at),
            ),
        )

    # -- internal -----------------------------------------------------------

    @property
    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _execute(self, sql: str, params: tuple = ()) -> None:
        self._connection.execute(sql, params)
        self._connection.commit()

    def _query_one(self, sql: str, params: tuple = ()) -> tuple | None:
        return self._connection.execute(sql, params).fetchone()


def _to_utc_text(dt: datetime) -> str:
    return dt.isoformat()
