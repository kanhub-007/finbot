"""SQLite migration runner — creates and migrates the Finbot schema."""

import os
import sqlite3

from finbot.core.domain.interfaces.database_migrator import DatabaseMigrator

# Ordered list of (version, sql) pairs.  Add new migrations at the end.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bot_runs (
            run_id        TEXT PRIMARY KEY,
            strategy_name TEXT NOT NULL,
            strategy_hash TEXT NOT NULL,
            symbol        TEXT NOT NULL,
            interval      TEXT NOT NULL,
            mode          TEXT NOT NULL,
            started_at    TEXT NOT NULL,
            ended_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS strategy_snapshots (
            snapshot_id   TEXT PRIMARY KEY,
            bot_run_id    TEXT NOT NULL REFERENCES bot_runs(run_id),
            strategy_hash TEXT NOT NULL,
            full_yaml     TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS processed_signals (
            signal_key    TEXT PRIMARY KEY,
            bot_run_id    TEXT NOT NULL,
            signal_action TEXT NOT NULL,
            bar_timestamp TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_intents (
            intent_id     TEXT PRIMARY KEY,
            signal_key    TEXT NOT NULL DEFAULT '',
            symbol        TEXT NOT NULL,
            side          TEXT NOT NULL,
            order_type    TEXT NOT NULL,
            size          TEXT NOT NULL,
            price         TEXT,
            stop_price    TEXT,
            reduce_only   INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_responses (
            response_id   TEXT PRIMARY KEY,
            intent_id     TEXT NOT NULL REFERENCES order_intents(intent_id),
            bot_run_id    TEXT NOT NULL,
            response_json TEXT NOT NULL,
            status        TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fills (
            fill_id       TEXT PRIMARY KEY,
            bot_run_id    TEXT NOT NULL,
            order_id      TEXT NOT NULL,
            symbol        TEXT NOT NULL,
            side          TEXT NOT NULL,
            size          TEXT NOT NULL,
            price         TEXT NOT NULL,
            fee           TEXT NOT NULL DEFAULT '0',
            filled_at     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reconciliations (
            reconciliation_id  TEXT PRIMARY KEY,
            bot_run_id         TEXT NOT NULL,
            position_matches   INTEGER NOT NULL,
            open_orders_match  INTEGER NOT NULL,
            exchange_state_json TEXT NOT NULL DEFAULT '{}',
            details            TEXT NOT NULL DEFAULT '',
            reconciled_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS risk_events (
            event_id      TEXT PRIMARY KEY,
            bot_run_id    TEXT NOT NULL,
            event_type    TEXT NOT NULL,
            signal_key    TEXT NOT NULL,
            decision      TEXT NOT NULL,
            reason        TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            entry_id         TEXT PRIMARY KEY,
            bot_run_id       TEXT NOT NULL,
            event_type       TEXT NOT NULL,
            event_data_json  TEXT NOT NULL,
            created_at       TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS order_lifecycles (
            order_id      TEXT PRIMARY KEY,
            symbol        TEXT NOT NULL,
            side          TEXT NOT NULL,
            original_size TEXT NOT NULL,
            remaining_size TEXT NOT NULL,
            filled_size   TEXT NOT NULL,
            state         TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_lifecycle_transitions (
            transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id      TEXT NOT NULL REFERENCES order_lifecycles(order_id),
            from_state    TEXT NOT NULL,
            to_state      TEXT NOT NULL,
            reason        TEXT NOT NULL DEFAULT '',
            occurred_at   TEXT NOT NULL
        );
        """,
    ),
    (
        3,
        """
        CREATE TABLE IF NOT EXISTS trades (
            position_id      TEXT PRIMARY KEY,
            bot_run_id       TEXT NOT NULL REFERENCES bot_runs(run_id),
            symbol           TEXT NOT NULL,
            side             TEXT NOT NULL,
            size             TEXT NOT NULL,
            entry_price      TEXT,
            opened_at        TEXT NOT NULL,
            status           TEXT NOT NULL,
            realized_pnl     TEXT NOT NULL DEFAULT '0',
            total_fee        TEXT NOT NULL DEFAULT '0',
            closed_at        TEXT,
            close_price      TEXT,
            strategy_hash    TEXT NOT NULL DEFAULT '',
            entry_signal_key TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_trades_symbol_status
            ON trades(symbol, status);
        CREATE INDEX IF NOT EXISTS idx_trades_closed_at
            ON trades(closed_at) WHERE status = 'closed';
        """,
    ),
    (
        4,
        """
        CREATE TABLE IF NOT EXISTS telegram_chats (
            chat_id               INTEGER PRIMARY KEY,
            user_id               INTEGER NOT NULL,
            registered_at         TEXT NOT NULL,
            notifications_enabled INTEGER NOT NULL DEFAULT 1
        );
        """,
    ),
]

LATEST_VERSION = max(v for v, _ in MIGRATIONS) if MIGRATIONS else 0


class SqliteMigrator(DatabaseMigrator):
    """Applies pending schema migrations to a SQLite database.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    """

    def __init__(self, db_path: str = "data/finbot.db") -> None:
        self._db_path = db_path
        # Instance-level copies so tests (and future callers) can inject a
        # controlled migration list. ``migrate`` reads ``self.MIGRATIONS``.
        self.MIGRATIONS: list[tuple[int, str]] = list(MIGRATIONS)
        self.LATEST_VERSION: int = LATEST_VERSION

    def migrate(self) -> int:
        """Apply every pending migration atomically.

        Each migration runs inside a single explicit transaction that also
        inserts its row into ``schema_version``. ``executescript()`` is not
        used because it issues an implicit COMMIT and runs outside any
        transaction — a SQL failure halfway would leave the schema
        half-applied. Instead the connection is put in manual transaction
        mode (``isolation_level=None``) and the migration SQL is executed
        statement-by-statement inside a ``BEGIN``/``COMMIT`` wrapper.

        Returns the highest applied version.
        """
        _ensure_directory(self._db_path)
        conn = sqlite3.connect(self._db_path)
        try:
            current = self._version_from_conn(conn)
            # Manual transaction control so the version INSERT and the
            # migration SQL share one atomic BEGIN/COMMIT.
            conn.isolation_level = None
            self._ensure_schema_version_table(conn)
            for version, sql in self.MIGRATIONS:
                if version > current:
                    self._apply_migration(conn, version, sql)
                    current = version
            return max(current, self.LATEST_VERSION)
        finally:
            conn.close()

    @staticmethod
    def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
        """Create the ``schema_version`` bookkeeping table if absent.

        Owned by the migrator (not by a migration) so synthetic migration
        lists in tests and future migration orderings don't depend on a
        specific migration creating it. ``CREATE TABLE IF NOT EXISTS`` is
        idempotent with the historical v1 DDL.
        """
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )

    @staticmethod
    def _apply_migration(conn: sqlite3.Connection, version: int, sql: str) -> None:
        """Run one migration's SQL + version insert in one transaction."""
        conn.execute("BEGIN")
        try:
            for statement in _split_sql_statements(sql):
                if statement.strip():
                    conn.execute(statement)
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                (version,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def current_version(self) -> int:
        if not os.path.exists(self._db_path):
            return 0
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                return self._version_from_conn(conn)
            finally:
                conn.close()
        except sqlite3.OperationalError:
            # Database doesn't exist yet or schema_version table absent.
            # Other errors (corruption, permissions) should propagate.
            return 0

    @staticmethod
    def _version_from_conn(conn: sqlite3.Connection) -> int:
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            return row[0] if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            return 0


def _ensure_directory(db_path: str) -> None:
    """Create parent directories so sqlite3.connect can create the file."""
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _split_sql_statements(sql: str) -> list[str]:
    """Split a migration script into individual ``;``-terminated statements.

    Migrations in this module are plain DDL with no embedded semicolons
    inside strings or triggers, so a simple ``;`` split (preserving each
    statement with its trailing semicolon for ``conn.execute``) is safe and
    keeps each statement atomic. Statements that are empty/whitespace-only
    are kept as-is; callers skip them.
    """
    # ``conn.execute`` accepts a single statement (no trailing ';'). Split,
    # drop the empty tail produced by a trailing newline, and strip ';'.
    raw = [s.strip() for s in sql.split(";") if s.strip()]
    return raw
