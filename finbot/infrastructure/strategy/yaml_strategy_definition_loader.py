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
        self._last_definition: StrategyDefinition | None = None

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
        self._last_definition = result.definition
        return result.definition

    def load_from_file(self, path: str) -> StrategyDefinition:
        content = self.load_content(path)
        return self.load_from_text(content)

    def load_content(self, path: str) -> str:
        """Read the raw strategy file content."""
        full = Path(path).resolve()
        if not full.is_file():
            raise FileNotFoundError(f"Strategy file not found: {path}")
        return full.read_text(encoding="utf-8")

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

    def parse_timeframes(self, content: str):
        """Parse the ``timeframes`` block from raw strategy YAML content.

        Returns a :class:`StrategyTimeframes` when the content declares a
        ``timeframes`` block with at least a primary interval, or ``None``
        for single-TF strategies.
        """
        import yaml

        from finbot.core.domain.entities.strategy_timeframes import (
            StrategyTimeframes,
        )

        try:
            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                return None
            tf = data.get("timeframes")
            if not isinstance(tf, dict):
                return None
            primary = tf.get("primary")
            if not primary:
                return None
            informatives: list[str] = []
            aliases: dict[str, str] = {}
            for item in tf.get("informative", []) or []:
                if isinstance(item, dict):
                    interval = item.get("interval")
                    alias = item.get("alias")
                    if interval:
                        informatives.append(interval)
                        if alias:
                            aliases[alias] = interval
            return StrategyTimeframes(
                primary=str(primary),
                informative_intervals=tuple(informatives),
                informative_aliases=aliases,
            )
        except Exception:
            return None

    def last_timeframes(self):
        """Return the timeframes declared by the last-loaded strategy.

        Returns ``None`` for single-TF strategies (no ``timeframes`` block)
        or when no strategy has been loaded yet.
        """
        from finbot.core.domain.services.strategy_timeframe_parser import (
            parse_timeframes,
        )

        if self._last_definition is None:
            return None
        return parse_timeframes(self._last_definition)
