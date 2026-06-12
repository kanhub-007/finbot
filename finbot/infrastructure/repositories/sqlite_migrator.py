"""SQLite migration runner — creates and migrates the Finbot schema."""

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

    def migrate(self) -> int:
        conn = sqlite3.connect(self._db_path)
        try:
            current = self._version_from_conn(conn)
            for version, sql in MIGRATIONS:
                if version > current:
                    conn.executescript(sql)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_version (version) " "VALUES (?)",
                        (version,),
                    )
                    conn.commit()
            return max(current, LATEST_VERSION)
        finally:
            conn.close()

    def current_version(self) -> int:
        import os

        if not os.path.exists(self._db_path):
            return 0
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                return self._version_from_conn(conn)
            finally:
                conn.close()
        except Exception:
            return 0

    @staticmethod
    def _version_from_conn(conn: sqlite3.Connection) -> int:
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            return row[0] if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            return 0
