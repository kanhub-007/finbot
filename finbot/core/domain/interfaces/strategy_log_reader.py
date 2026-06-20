"""StrategyLogReader — read strategy evaluation logs."""

from abc import ABC, abstractmethod
from typing import Any


class StrategyLogReader(ABC):
    """Read tail entries from strategy evaluation logs."""

    @abstractmethod
    def list_logs(self) -> list[str]:
        """Return names of available log files."""

    @abstractmethod
    def read_tail(
        self, strategy_file: str, symbol: str, n: int = 20
    ) -> list[dict[str, Any]]:
        """Return the last *n* log entries."""

    @staticmethod
    def parse_log_name(name: str) -> tuple[str, str]:
        """Split log file stem into (strategy_slug, symbol)."""
        return name, "?"
