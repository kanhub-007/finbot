"""Startup validation — checks DB schema version before bot execution."""

from finbot.infrastructure.repositories.sqlite_migrator import (
    LATEST_VERSION,
    SqliteMigrator,
)


def validate_db_schema(db_path: str) -> None:
    """Raise :class:`RuntimeError` if the database schema is outdated.

    Migrations are *not* applied automatically here — that is done by the
    companion :func:`run_migrations` function.  This check exists so the
    bot refuses to run against an un-migrated database.
    """
    migrator = SqliteMigrator(db_path)
    current = migrator.current_version()
    if current < LATEST_VERSION:
        raise RuntimeError(
            f"Database schema version {current} is behind "
            f"latest version {LATEST_VERSION}. "
            f"Run migrations first."
        )


def run_migrations(db_path: str) -> int:
    """Apply all pending migrations and return the new version."""
    return SqliteMigrator(db_path).migrate()
