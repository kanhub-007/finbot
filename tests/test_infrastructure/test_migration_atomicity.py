"""Atomicity tests for SqliteMigrator.migrate() (S2: M4).

``sqlite3.Connection.executescript()`` issues an implicit COMMIT before
running and runs outside any transaction. A migration whose SQL fails
halfway can therefore leave the schema half-applied AND still record its
version as applied. These tests pin the contract: a failing migration
rolls back fully, does not bump ``schema_version``, and can be retried
after the SQL is fixed.
"""

from __future__ import annotations

import pytest

from finbot.infrastructure.repositories.sqlite_migrator import SqliteMigrator


def _tables(conn) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


class TestAtomicMigrations:
    def test_failing_migration_is_rolled_back_and_version_not_incremented(
        self, tmp_path
    ) -> None:
        """A syntax-error migration must not leave tables or bump version.

        The first ``migrate()`` applies v1 (commits), then attempts v2 and
        fails halfway. v2's effects roll back, ``migrate`` re-raises, and
        ``schema_version`` stays at 1.
        """
        db = str(tmp_path / "atomic.db")
        good = "CREATE TABLE a (x INTEGER);"
        bad = "CREATE TABLE b (y INTEGER); CREATE TABEL broken;"
        migrator = SqliteMigrator(db)
        migrator.MIGRATIONS = [(1, good), (2, bad)]
        migrator.LATEST_VERSION = 2

        # Applies v1, then fails on v2 (rolled back) and re-raises.
        with pytest.raises(Exception):
            migrator.migrate()

        import sqlite3

        conn = sqlite3.connect(db)
        try:
            tables = _tables(conn)
            assert "a" in tables  # v1 survived
            assert "b" not in tables  # v2's table rolled back
        finally:
            conn.close()
        assert migrator.current_version() == 1  # v2 did not bump version

    def test_retry_after_fix_applies_migration_cleanly(self, tmp_path) -> None:
        """After the SQL is fixed, re-running migrate() succeeds."""
        db = str(tmp_path / "retry.db")
        good = "CREATE TABLE a (x INTEGER);"
        bad = "CREATE TABLE b (y INTEGER); CREATE TABEL broken;"
        migrator = SqliteMigrator(db)
        migrator.MIGRATIONS = [(1, good), (2, bad)]
        migrator.LATEST_VERSION = 2

        with pytest.raises(Exception):
            migrator.migrate()
        assert migrator.current_version() == 1

        # Fix the SQL and retry — v2 now applies cleanly.
        migrator.MIGRATIONS = [(1, good), (2, "CREATE TABLE b (y INTEGER);")]
        migrator.migrate()
        assert migrator.current_version() == 2

    def test_index_failure_rolls_back_table_creation(self, tmp_path) -> None:
        """A migration that creates a table then fails at index creation
        must roll back the table too (single transaction)."""
        db = str(tmp_path / "idx.db")
        sql = (
            "CREATE TABLE c (z INTEGER);\n"
            "CREATE INDEX bad ON nonexistent_table(column);\n"
        )
        migrator = SqliteMigrator(db)
        migrator.MIGRATIONS = [(1, sql)]
        migrator.LATEST_VERSION = 1

        with pytest.raises(Exception):
            migrator.migrate()

        import sqlite3

        conn = sqlite3.connect(db)
        try:
            tables = _tables(conn)
            assert "c" not in tables  # table rolled back with the failed index
        finally:
            conn.close()
        assert migrator.current_version() == 0

    def test_version_insert_uses_instance_migrations(self, tmp_path) -> None:
        """migrate() must read self.MIGRATIONS (testability) so callers can
        inject a controlled migration list.

        Also asserts the schema_version table ends with exactly one row per
        applied version (no duplicate inserts from a non-atomic retry).
        """
        db = str(tmp_path / "versioned.db")
        migrator = SqliteMigrator(db)
        migrator.MIGRATIONS = [(1, "CREATE TABLE d (w INTEGER);")]
        migrator.LATEST_VERSION = 1

        migrator.migrate()
        assert migrator.current_version() == 1

        import sqlite3

        conn = sqlite3.connect(db)
        try:
            rows = conn.execute("SELECT version FROM schema_version").fetchall()
            assert [r[0] for r in rows] == [1]  # exactly one row
        finally:
            conn.close()
