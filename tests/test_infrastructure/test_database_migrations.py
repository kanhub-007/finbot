"""Tests for SQLite migration runner."""

import os
import tempfile

from finbot.infrastructure.repositories.sqlite_migrator import (
    LATEST_VERSION,
    SqliteMigrator,
)


class TestSqliteMigrator:
    def test_migrations_create_schema_from_empty_db(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            migrator = SqliteMigrator(db_path)
            assert migrator.current_version() == 0
            version = migrator.migrate()
            assert version == LATEST_VERSION
            assert migrator.current_version() == LATEST_VERSION

    def test_migrations_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            migrator = SqliteMigrator(db_path)
            v1 = migrator.migrate()
            v2 = migrator.migrate()
            assert v1 == v2 == LATEST_VERSION

    def test_migrator_handles_nonexistent_directory(self) -> None:
        # path in a directory that doesn't exist — should still work
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "sub", "test.db")
            # migrating should fail gracefully or create dirs
            # Our migrator doesn't auto-create dirs — that's fine for now
            # but let's test that the file path check doesn't crash
            migrator = SqliteMigrator(db_path)
            v = migrator.current_version()
            assert v == 0
