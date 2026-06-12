"""Tests for startup schema validation."""

import os
import tempfile

import pytest

from finbot.startup.db import run_migrations, validate_db_schema


class TestStartupDbValidation:
    def test_migrate_then_validate_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            run_migrations(db_path)
            # Should not raise
            validate_db_schema(db_path)

    def test_validate_without_migrations_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            # Create file but don't migrate
            with open(db_path, "w") as f:
                f.write("")
            with pytest.raises(RuntimeError, match="behind"):
                validate_db_schema(db_path)

    def test_validate_on_nonexistent_db_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "no_such_dir", "test.db")
            with pytest.raises(RuntimeError, match="behind"):
                validate_db_schema(db_path)
