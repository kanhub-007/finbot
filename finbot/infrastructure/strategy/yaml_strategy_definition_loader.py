"""YAML strategy definition loader implementation."""

from pathlib import Path

from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.entities.strategy_load_error import StrategyLoadError
from finbot.core.domain.interfaces.strategy_definition_loader import (
    StrategyDefinitionLoader,
)
from finbot.infrastructure.strategy.strategy_definition_parser import (
    StrategyDefinitionParser,
)


class YamlStrategyDefinitionLoader(StrategyDefinitionLoader):
    """Load Finbot YAML/JSON strategy files via the parser stack."""

    def __init__(self, parser: StrategyDefinitionParser | None = None):
        self._parser = parser or StrategyDefinitionParser()

    def load_from_text(self, content: str) -> StrategyDefinition:
        result = self._parser.parse(content)
        if not result.valid:
            messages = "; ".join(e.message for e in result.errors)
            raise StrategyLoadError(f"Strategy validation failed: {messages}")
        if result.definition is None:
            raise StrategyLoadError(
                "Strategy validation passed but no definition returned"
            )
        return result.definition

    def load_from_file(self, path: str) -> StrategyDefinition:
        full = Path(path).resolve()
        if not full.is_file():
            raise FileNotFoundError(f"Strategy file not found: {path}")
        content = full.read_text(encoding="utf-8")
        return self.load_from_text(content)
