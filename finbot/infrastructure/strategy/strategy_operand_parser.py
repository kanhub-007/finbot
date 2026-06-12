"""StrategyOperandParser — parse condition operands."""

from typing import Any

from finbot.core.domain.entities.operand import Operand
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)
from finbot.core.domain.interfaces.indicator_capability_provider import (
    IndicatorCapabilityProvider,
)
from finbot.infrastructure.strategy.strategy_definition_parse_helpers import (
    OHLCV_FIELDS,
    make_error,
    resolve_expression,
)


class StrategyOperandParser:
    """Parse shorthand or canonical condition operands."""

    def __init__(self, catalog: IndicatorCapabilityProvider):
        """Create an operand parser backed by indicator capabilities."""
        self._catalog = catalog

    def parse(
        self,
        raw: Any,
        aliases: dict[str, str],
        sources_map: dict[str, list[str]],
        feature_aliases: dict[str, str],
        resolved_params: dict[str, Any],
        path: str,
        errors: list[StrategyValidationError],
    ) -> Operand:
        """Parse one operand into canonical form."""
        value = resolve_expression(raw, resolved_params, path, errors)
        if isinstance(value, (int, float, bool, list)):
            return Operand(kind="literal", value=value, label=str(raw))
        if isinstance(value, str):
            return self._parse_named(
                value, aliases, sources_map, feature_aliases, path, errors
            )
        errors.append(make_error(path, "operand is required"))
        return Operand(kind="literal", value=0, label=str(raw))

    def _parse_named(
        self,
        value: str,
        aliases: dict[str, str],
        sources_map: dict[str, list[str]],
        feature_aliases: dict[str, str],
        path: str,
        errors: list[StrategyValidationError],
    ) -> Operand:
        if value in aliases:
            resolved = aliases[value]
            fallback = sources_map.get(resolved, [])
            return Operand(
                kind="indicator",
                value=resolved,
                label=value,
                sources=fallback,
            )
        if value in feature_aliases:
            return Operand(kind="feature", value=feature_aliases[value], label=value)
        if value in OHLCV_FIELDS:
            return Operand(kind="field", value=value, label=value)
        if self._catalog.supports_concrete(value):
            return Operand(kind="column", value=value, label=value)
        errors.append(make_error(path, f"unknown operand '{value}'", "unknown_operand"))
        return Operand(kind="literal", value=0, label=value)
