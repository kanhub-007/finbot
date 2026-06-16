"""FilesystemStrategyDirectory — reads strategy files from disk."""

from __future__ import annotations

from pathlib import Path

from finbot.core.domain.interfaces.strategy_directory import StrategyDirectory


class FilesystemStrategyDirectory(StrategyDirectory):
    """Implements StrategyDirectory by listing .yaml/.yml files from a directory.

    Used by the Telegram bot to show available strategies and validate
    user selections before starting a bot.
    """

    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)

    def list_strategies(self) -> list[str]:
        """Return sorted list of .yaml/.yml filenames in the directory."""
        if not self._dir.exists():
            return []
        return sorted(
            f.name
            for f in self._dir.iterdir()
            if f.is_file() and f.suffix.lower() in (".yaml", ".yml")
        )

    def strategy_exists(self, name: str) -> bool:
        """Check if a strategy file exists by name."""
        return (self._dir / name).is_file()

    def get_strategy_path(self, name: str) -> str:
        """Return the full path of a strategy by name."""
        return str(self._dir / name)
