"""YAML strategy definition loader implementation."""

from pathlib import Path

from finbar_strategy_runtime.domain.entities.strategy_definition import (
    StrategyDefinition,
)
from finbar_strategy_runtime.domain.entities.strategy_validation_result import (
    StrategyValidationResult,
)
from finbar_strategy_runtime.parser.strategy_definition_parser import (
    StrategyDefinitionParser,
)

from finbot.core.domain.entities.strategy_load_error import StrategyLoadError
from finbot.core.domain.interfaces.strategy_definition_loader import (
    StrategyDefinitionLoader,
)


class YamlStrategyDefinitionLoader(StrategyDefinitionLoader):
    """Load Finbot YAML/JSON strategy files via the shared package parser.

    Retains the last :class:`StrategyValidationResult` so callers can read
    ``required_columns`` — the concrete enriched columns the package
    computes (e.g. ``vp_vah``), not the strategy-local aliases.
    """

    def __init__(self, parser: StrategyDefinitionParser | None = None):
        self._parser = parser or StrategyDefinitionParser()
        self._last_result: StrategyValidationResult | None = None

    def load_from_text(self, content: str) -> StrategyDefinition:
        result = self._parser.parse(content)
        self._last_result = result
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

    def last_required_columns(self) -> list[str]:
        """Concrete enriched columns required by the last-loaded strategy.

        Sourced from the package validation result's ``required_columns`` —
        the columns directly referenced by condition trees / risk stops
        (e.g. ``atr``, ``above_value``). Used by Finbot's EnrichmentValidator.
        Returns an empty list when nothing has been loaded yet.
        """
        if self._last_result is None:
            return []
        return list(self._last_result.required_columns)

    def last_required_indicators(self) -> list[str]:
        """All concrete indicators declared by the last-loaded strategy.

        Sourced from the package validation result's ``required_indicators``
        — every declared indicator's concrete column name, including
        intermediate indicators (e.g. ``vp_vah``/``vp_val``) that only feed
        composites (``above_value``). Used by Finbot's IndicatorCalculator,
        which must be asked to compute the full chain or the composites read
        NaN. Distinct from :meth:`last_required_columns`.
        Returns an empty list when nothing has been loaded yet.
        """
        if self._last_result is None:
            return []
        return list(self._last_result.required_indicators)
