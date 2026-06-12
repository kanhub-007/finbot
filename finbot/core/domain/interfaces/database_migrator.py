"""Database migrator interface."""

from abc import ABC, abstractmethod


class DatabaseMigrator(ABC):
    """Runs schema migrations idempotently on a SQL database.

    Every migration is a numbered step applied exactly once.
    """

    @abstractmethod
    def migrate(self) -> int:
        """Apply all pending migrations and return the new version.

        Returns 0 if no migrations were pending and the database
        is already at the latest version.
        """

    @abstractmethod
    def current_version(self) -> int:
        """Return the current schema version, or 0 if uninitialised."""
