"""SQLite bot state repository — persists all bot state to a local SQLite DB."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from datetime import date as _date
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
from finbot.core.domain.entities.order_state import OrderState
from finbot.core.domain.entities.position_direction import (
    PositionDirection,
)
from finbot.core.domain.entities.processed_signal import ProcessedSignal
from finbot.core.domain.entities.reconciliation_record import (
    ReconciliationRecord,
)
from finbot.core.domain.entities.risk_event_record import RiskEventRecord
from finbot.core.domain.entities.strategy_snapshot import StrategySnapshot
from finbot.core.domain.entities.trade import Trade
from finbot.core.domain.interfaces.bot_state_repository import (
    BotStateRepository,
)
from finbot.infrastructure.repositories.sqlite_migrator import (
    _ensure_directory,
)

_TRADE_COLS = (
    "position_id, bot_run_id, symbol, side, size, entry_price, opened_at, "
    "status, realized_pnl, total_fee, closed_at, close_price, "
    "strategy_hash, entry_signal_key"
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
        self._in_transaction = False

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
        block exits without exception. Inner write methods call
        :meth:`_execute`, which honours ``self._in_transaction`` and skips
        the per-call commit so nothing is persisted prematurely.

        **Nested re-entry** (L5): when already inside a transaction, the
        context manager yields as a no-op passthrough — inner writes still
        hit ``_execute`` (which sees ``_in_transaction=True`` and skips
        commit), and the outer ``transaction()`` owns the single BEGIN/COMMIT.
        This means callers can safely wrap a transaction around code that
        already opened one without double-committing or deadlocking.
        """
        if self._in_transaction:
            # Nested re-entry: behave as a no-op passthrough so callers can
            # wrap a transaction around code that already opened one.
            yield
            return
        conn = self._connection
        try:
            self._in_transaction = True
            conn.commit()  # flush any pending autocommit writes first
            conn.execute("BEGIN")
            yield
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._in_transaction = False

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

    # -- status queries ----------------------------------------------------

    def get_latest_bot_run(self) -> BotRun | None:
        row = self._query_one(
            "SELECT run_id, strategy_name, strategy_hash, symbol, "
            "interval, mode, started_at, ended_at "
            "FROM bot_runs ORDER BY started_at DESC LIMIT 1"
        )
        if row is None:
            return None
        return BotRun(
            run_id=row[0],
            strategy_name=row[1],
            strategy_hash=row[2],
            symbol=row[3],
            interval=row[4],
            mode=row[5],
            started_at=datetime.fromisoformat(row[6]),
            ended_at=(datetime.fromisoformat(row[7]) if row[7] else None),
        )

    # -- active symbol persistence (trading-control spec) ------------------

    def _ensure_active_symbol_table(self) -> None:
        """Create the single-row active_symbol table if absent."""
        self._execute(
            "CREATE TABLE IF NOT EXISTS active_symbol ("
            "id INTEGER PRIMARY KEY CHECK (id = 1),"
            "symbol TEXT NOT NULL,"
            "leverage INTEGER NOT NULL,"
            "margin_mode TEXT NOT NULL)"
        )

    def save_active_symbol(self, state) -> None:
        """Persist (overwrite) the single active-symbol row."""

        self._ensure_active_symbol_table()
        self._execute(
            "INSERT INTO active_symbol (id, symbol, leverage, margin_mode) "
            "VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "symbol=excluded.symbol, leverage=excluded.leverage, "
            "margin_mode=excluded.margin_mode",
            (state.symbol, state.leverage, state.margin_mode),
        )

    def load_active_symbol(self):
        """Return the persisted active symbol, or None if idle."""
        from finbot.core.domain.entities.active_symbol_state import (
            ActiveSymbolState,
        )

        self._ensure_active_symbol_table()
        row = self._query_one(
            "SELECT symbol, leverage, margin_mode FROM active_symbol WHERE id=1"
        )
        if row is None:
            return None
        return ActiveSymbolState(symbol=row[0], leverage=row[1], margin_mode=row[2])

    def clear_active_symbol(self) -> None:
        """Delete the persisted active-symbol row."""
        self._ensure_active_symbol_table()
        self._execute("DELETE FROM active_symbol WHERE id=1")

    def get_last_signal(self) -> ProcessedSignal | None:
        row = self._query_one(
            "SELECT signal_key, bot_run_id, signal_action, bar_timestamp, "
            "created_at "
            "FROM processed_signals ORDER BY created_at DESC LIMIT 1"
        )
        if row is None:
            return None
        return ProcessedSignal(
            signal_key=row[0],
            bot_run_id=row[1],
            signal_action=row[2],
            bar_timestamp=row[3],
            created_at=datetime.fromisoformat(row[4]),
        )

    def get_last_order_response(
        self,
    ) -> OrderResponseRecord | None:
        row = self._query_one(
            "SELECT response_id, intent_id, bot_run_id, response_json, "
            "status, created_at "
            "FROM order_responses ORDER BY created_at DESC LIMIT 1"
        )
        if row is None:
            return None
        return OrderResponseRecord(
            response_id=row[0],
            intent_id=row[1],
            bot_run_id=row[2],
            response_json=row[3],
            status=row[4],
            created_at=datetime.fromisoformat(row[5]),
        )

    def count_signals(self) -> int:
        row = self._query_one("SELECT COUNT(*) FROM processed_signals")
        return row[0] if row else 0

    def count_orders(self) -> int:
        row = self._query_one("SELECT COUNT(*) FROM order_intents")
        return row[0] if row else 0

    def count_fills(self) -> int:
        row = self._query_one("SELECT COUNT(*) FROM fills")
        return row[0] if row else 0

    def has_fill(self, fill_id: str) -> bool:
        row = self._query_one("SELECT 1 FROM fills WHERE fill_id = ?", (fill_id,))
        return row is not None

    def get_order_lifecycle(self, order_id: str) -> OrderLifecycle | None:
        row = self._query_one(
            "SELECT order_id, symbol, side, original_size, remaining_size, "
            "filled_size, state FROM order_lifecycles WHERE order_id = ?",
            (order_id,),
        )
        if row is None:
            return None
        return _lifecycle_from_row(row)

    # -- run history queries -------------------------------------------------

    def get_bot_run(self, run_id: str) -> BotRun | None:
        row = self._query_one(
            "SELECT run_id, strategy_name, strategy_hash, symbol, "
            "interval, mode, started_at, ended_at "
            "FROM bot_runs WHERE run_id = ?",
            (run_id,),
        )
        if row is None:
            return None
        return _bot_run_from_row(row)

    def list_bot_runs(
        self, limit: int = 20, mode_filter: str | None = None
    ) -> list[BotRun]:
        sql = (
            "SELECT run_id, strategy_name, strategy_hash, symbol, "
            "interval, mode, started_at, ended_at "
            "FROM bot_runs "
        )
        params: tuple = ()
        if mode_filter:
            sql += "WHERE mode = ? "
            params = (mode_filter,)
        sql += "ORDER BY started_at DESC LIMIT ?"
        params = params + (limit,)
        rows = self._connection.execute(sql, params).fetchall()
        return [_bot_run_from_row(r) for r in rows]

    def get_signals_for_run(self, run_id: str) -> list[ProcessedSignal]:
        rows = self._connection.execute(
            "SELECT signal_key, bot_run_id, signal_action, bar_timestamp, "
            "created_at FROM processed_signals WHERE bot_run_id = ? "
            "ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [
            ProcessedSignal(
                signal_key=r[0],
                bot_run_id=r[1],
                signal_action=r[2],
                bar_timestamp=r[3],
                created_at=datetime.fromisoformat(r[4]),
            )
            for r in rows
        ]

    def get_orders_for_run(self, run_id: str) -> list[OrderResponseRecord]:
        rows = self._connection.execute(
            "SELECT response_id, intent_id, bot_run_id, response_json, "
            "status, created_at FROM order_responses WHERE bot_run_id = ? "
            "ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [
            OrderResponseRecord(
                response_id=r[0],
                intent_id=r[1],
                bot_run_id=r[2],
                response_json=r[3],
                status=r[4],
                created_at=datetime.fromisoformat(r[5]),
            )
            for r in rows
        ]

    def get_fills_for_run(self, run_id: str) -> list[FillRecord]:
        rows = self._connection.execute(
            "SELECT fill_id, bot_run_id, order_id, symbol, side, size, price, "
            "fee, filled_at FROM fills WHERE bot_run_id = ? "
            "ORDER BY filled_at",
            (run_id,),
        ).fetchall()
        return [_fill_from_row(r) for r in rows]

    def get_run_counts(self, run_ids: list[str]) -> dict[str, RunCounts]:
        """Return per-run signal/order/fill counts via GROUP BY (not N+1).

        Three queries total regardless of how many runs are requested,
        replacing the prior pattern of three ``fetchall``-per-run calls in
        list endpoints (which transferred every row just to take ``len()``).
        """
        counts: dict[str, list[int]] = {rid: [0, 0, 0] for rid in run_ids}
        if not run_ids:
            return {rid: RunCounts(*c) for rid, c in counts.items()}

        placeholders = ",".join("?" for _ in run_ids)
        params = tuple(run_ids)
        # (table, result index) — orders come from order_responses since
        # order_intents has no bot_run_id column.
        per_table = (
            ("processed_signals", 0),
            ("order_responses", 1),
            ("fills", 2),
        )
        for table, idx in per_table:
            rows = self._connection.execute(
                f"SELECT bot_run_id, COUNT(*) FROM {table} "
                f"WHERE bot_run_id IN ({placeholders}) GROUP BY bot_run_id",
                params,
            ).fetchall()
            for rid, n in rows:
                if rid in counts:
                    counts[rid][idx] = int(n)
        return {rid: RunCounts(*c) for rid, c in counts.items()}

    def get_risk_events_for_run(self, run_id: str) -> list[RiskEventRecord]:
        rows = self._connection.execute(
            "SELECT event_id, bot_run_id, event_type, signal_key, decision, "
            "reason, created_at FROM risk_events WHERE bot_run_id = ? "
            "ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [_risk_event_from_row(r) for r in rows]

    def get_audit_log(
        self, limit: int = 50, event_type: str | None = None
    ) -> list[AuditLogEntry]:
        sql = (
            "SELECT entry_id, bot_run_id, event_type, event_data_json, created_at "
            "FROM audit_log "
        )
        params: tuple = ()
        if event_type:
            sql += "WHERE event_type = ? "
            params = (event_type,)
        sql += "ORDER BY created_at DESC LIMIT ?"
        params = params + (limit,)
        rows = self._connection.execute(sql, params).fetchall()
        return [_audit_from_row(r) for r in rows]

    def save_order_lifecycle(self, lifecycle: OrderLifecycle) -> None:
        now_text = _to_utc_text(datetime.now(UTC))
        self._execute(
            "INSERT INTO order_lifecycles "
            "(order_id, symbol, side, original_size, remaining_size, "
            "filled_size, state, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(order_id) DO UPDATE SET "
            "symbol=excluded.symbol, side=excluded.side, "
            "original_size=excluded.original_size, "
            "remaining_size=excluded.remaining_size, "
            "filled_size=excluded.filled_size, state=excluded.state, "
            "updated_at=excluded.updated_at",
            (
                lifecycle.order_id,
                lifecycle.symbol,
                lifecycle.side,
                str(lifecycle.original_size),
                str(lifecycle.remaining_size),
                str(lifecycle.filled_size),
                lifecycle.state.value,
                now_text,
                now_text,
            ),
        )
        for from_state, to_state, reason in lifecycle.unpersisted_transitions:
            self._execute(
                "INSERT INTO order_lifecycle_transitions "
                "(order_id, from_state, to_state, reason, occurred_at) "
                "VALUES (?,?,?,?,?)",
                (
                    lifecycle.order_id,
                    from_state.value,
                    to_state.value,
                    reason,
                    now_text,
                ),
            )
        # Mark the inserted transitions as persisted so the next save only
        # appends new ones — avoids O(k²) re-insertion over an order's life.
        lifecycle.persisted_transition_count = len(lifecycle.transition_history)

    def list_open_order_lifecycles(
        self, symbol: str | None = None
    ) -> list[OrderLifecycle]:
        """Return lifecycles in an active state, optionally filtered by symbol.

        Used by startup reconciliation to detect local lifecycles the
        exchange no longer reports (stale rows after a crash/restart).
        """
        from finbot.core.domain.entities.order_state import ACTIVE_ORDER_STATES

        placeholders = ",".join("?" for _ in ACTIVE_ORDER_STATES)
        states = tuple(s.value for s in ACTIVE_ORDER_STATES)
        sql = (
            f"SELECT order_id, symbol, side, original_size, remaining_size, "
            f"filled_size, state FROM order_lifecycles "
            f"WHERE state IN ({placeholders})"
        )
        params: tuple = states
        if symbol is not None:
            sql += " AND symbol = ?"
            params = states + (symbol,)
        sql += " ORDER BY created_at"
        rows = self._connection.execute(sql, params).fetchall()
        return [_lifecycle_from_row(r) for r in rows]

    # -- trades ---------------------------------------------------------------

    def open_trade(self, trade: Trade) -> None:
        self._execute(
            "INSERT INTO trades (position_id, bot_run_id, symbol, side, "
            "size, entry_price, opened_at, status, realized_pnl, total_fee, "
            "closed_at, close_price, strategy_hash, entry_signal_key) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                trade.position_id,
                trade.bot_run_id,
                trade.symbol,
                trade.side.value,
                str(trade.size),
                str(trade.entry_price) if trade.entry_price is not None else None,
                _to_utc_text(trade.opened_at),
                trade.status,
                str(trade.realized_pnl),
                str(trade.total_fee),
                _to_utc_text(trade.closed_at) if trade.closed_at else None,
                str(trade.close_price) if trade.close_price is not None else None,
                trade.strategy_hash,
                trade.entry_signal_key,
            ),
        )

    def update_trade(self, trade: Trade) -> None:
        self._execute(
            "UPDATE trades SET bot_run_id=?, symbol=?, side=?, size=?, "
            "entry_price=?, opened_at=?, status=?, realized_pnl=?, "
            "total_fee=?, closed_at=?, close_price=?, "
            "strategy_hash=?, entry_signal_key=? "
            "WHERE position_id=?",
            (
                trade.bot_run_id,
                trade.symbol,
                trade.side.value,
                str(trade.size),
                str(trade.entry_price) if trade.entry_price is not None else None,
                _to_utc_text(trade.opened_at),
                trade.status,
                str(trade.realized_pnl),
                str(trade.total_fee),
                _to_utc_text(trade.closed_at) if trade.closed_at else None,
                str(trade.close_price) if trade.close_price is not None else None,
                trade.strategy_hash,
                trade.entry_signal_key,
                trade.position_id,
            ),
        )

    def get_open_trade(self, symbol: str) -> Trade | None:
        row = self._query_one(
            f"SELECT {_TRADE_COLS} FROM trades "
            "WHERE symbol=? AND status='open' ORDER BY opened_at DESC LIMIT 1",
            (symbol,),
        )
        return _trade_from_row(row) if row else None

    def list_open_trades(self) -> list[Trade]:
        rows = self._connection.execute(
            f"SELECT {_TRADE_COLS} FROM trades "
            "WHERE status='open' ORDER BY opened_at DESC"
        ).fetchall()
        return [_trade_from_row(r) for r in rows]

    def list_closed_trades(self, *, bot_run_id: str | None = None) -> list[Trade]:
        if bot_run_id is not None:
            rows = self._connection.execute(
                f"SELECT {_TRADE_COLS} FROM trades "
                "WHERE status='closed' AND bot_run_id=? "
                "ORDER BY closed_at DESC",
                (bot_run_id,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                f"SELECT {_TRADE_COLS} FROM trades "
                "WHERE status='closed' ORDER BY closed_at DESC"
            ).fetchall()
        return [_trade_from_row(r) for r in rows]

    def realized_loss_on(self, day: _date) -> Decimal:
        """Sum of absolute realized losses for trades closed on *day*.

        Loads matching rows and sums with Decimal arithmetic to avoid
        precision loss from CAST to REAL.
        """
        day_start = _to_utc_text(datetime(day.year, day.month, day.day, tzinfo=UTC))
        day_end = _to_utc_text(
            datetime(day.year, day.month, day.day, 23, 59, 59, 999999, tzinfo=UTC)
        )
        rows = self._connection.execute(
            "SELECT realized_pnl FROM trades "
            "WHERE status='closed' AND closed_at >= ? AND closed_at <= ?",
            (day_start, day_end),
        ).fetchall()
        total = Decimal("0")
        for (pnl_text,) in rows:
            pnl = Decimal(str(pnl_text))
            if pnl < Decimal("0"):
                total += pnl
        return abs(total)

    @property
    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            _ensure_directory(self._db_path)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _execute(self, sql: str, params: tuple = ()) -> None:
        self._connection.execute(sql, params)
        if not self._in_transaction:
            self._connection.commit()

    def _query_one(self, sql: str, params: tuple = ()) -> tuple | None:
        return self._connection.execute(sql, params).fetchone()


def _to_utc_text(dt: datetime) -> str:
    return dt.isoformat()


def _lifecycle_from_row(row: tuple) -> OrderLifecycle:
    """Map an ``order_lifecycles`` row to a domain :class:`OrderLifecycle`."""
    return OrderLifecycle(
        order_id=row[0],
        symbol=row[1],
        side=row[2],
        original_size=Decimal(row[3]),
        remaining_size=Decimal(row[4]),
        filled_size=Decimal(row[5]),
        state=OrderState(row[6]),
    )


def _bot_run_from_row(row: tuple) -> BotRun:
    """Map a ``bot_runs`` row to a domain :class:`BotRun`."""
    return BotRun(
        run_id=row[0],
        strategy_name=row[1],
        strategy_hash=row[2],
        symbol=row[3],
        interval=row[4],
        mode=row[5],
        started_at=datetime.fromisoformat(row[6]),
        ended_at=datetime.fromisoformat(row[7]) if row[7] else None,
    )


def _fill_from_row(row: tuple) -> FillRecord:
    """Map a ``fills`` row to a domain :class:`FillRecord`."""
    return FillRecord(
        fill_id=row[0],
        bot_run_id=row[1],
        order_id=row[2],
        symbol=row[3],
        side=row[4],
        size=Decimal(row[5]),
        price=Decimal(row[6]),
        fee=Decimal(row[7]),
        filled_at=datetime.fromisoformat(row[8]),
    )


def _risk_event_from_row(row: tuple) -> RiskEventRecord:
    """Map a ``risk_events`` row to a domain :class:`RiskEventRecord`."""
    return RiskEventRecord(
        event_id=row[0],
        bot_run_id=row[1],
        event_type=row[2],
        signal_key=row[3],
        decision=row[4],
        reason=row[5] if row[5] else "",
        created_at=datetime.fromisoformat(row[6]),
    )


def _audit_from_row(row: tuple) -> AuditLogEntry:
    """Map an ``audit_log`` row to a domain :class:`AuditLogEntry`."""
    return AuditLogEntry(
        entry_id=row[0],
        bot_run_id=row[1],
        event_type=row[2],
        event_data_json=row[3],
        created_at=datetime.fromisoformat(row[4]),
    )


def _trade_from_row(row: tuple) -> Trade:
    """Map a ``trades`` row to a domain :class:`Trade`."""
    return Trade(
        position_id=row[0],
        bot_run_id=row[1],
        symbol=row[2],
        side=PositionDirection(row[3]),
        size=Decimal(str(row[4])),
        entry_price=Decimal(str(row[5])) if row[5] is not None else None,
        opened_at=datetime.fromisoformat(row[6]),
        status=row[7],
        realized_pnl=Decimal(str(row[8])),
        total_fee=Decimal(str(row[9])),
        closed_at=datetime.fromisoformat(row[10]) if row[10] else None,
        close_price=Decimal(str(row[11])) if row[11] is not None else None,
        strategy_hash=row[12],
        entry_signal_key=row[13],
    )
