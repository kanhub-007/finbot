"""StrategyDirectory — interface for listing available strategy files."""

from abc import ABC, abstractmethod


class StrategyDirectory(ABC):
    """Interface for discovering strategy YAML files on the filesystem.

    Used by the /run and /list Telegram commands to show
    available strategies and validate selections.
    """

    @abstractmethod
    def list_strategies(self) -> list[str]: ...

    @abstractmethod
    def strategy_exists(self, name: str) -> bool: ...

    @abstractmethod
    def get_strategy_path(self, name: str) -> str: ...
