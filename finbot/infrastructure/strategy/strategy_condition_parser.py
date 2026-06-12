"""StrategyConditionParser — parse side rule condition trees."""

from typing import Any

from finbot.core.domain.entities.condition_group import ConditionGroup
from finbot.core.domain.entities.feature_spec import FeatureSpec
from finbot.core.domain.entities.indicator_spec import IndicatorSpec
from finbot.core.domain.entities.side_rules import SideRules
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)
from finbot.core.domain.interfaces.indicator_capability_provider import (
    IndicatorCapabilityProvider,
)
from finbot.infrastructure.strategy.strategy_condition_group_parser import (
    StrategyConditionGroupParser,
)
from finbot.infrastructure.strategy.strategy_definition_parse_helpers import (
    extract_condition,
    make_error,
)
from finbot.infrastructure.strategy.strategy_indicator_catalog import (
    StrategyIndicatorCatalog,
)
from finbot.infrastructure.strategy.strategy_operand_parser import (
    StrategyOperandParser,
)


class StrategyConditionParser:
    """Parse side-specific entry/exit condition trees."""

    def __init__(self, catalog: IndicatorCapabilityProvider | None = None):
        """Create a condition parser backed by indicator capabilities."""
        self._catalog = catalog or StrategyIndicatorCatalog()
        operand_parser = StrategyOperandParser(self._catalog)
        self._group_parser = StrategyConditionGroupParser(operand_parser)

    def parse_sides(
        self,
        raw: Any,
        indicators: list[IndicatorSpec],
        features: list[FeatureSpec],
        resolved_params: dict[str, Any],
        errors: list[StrategyValidationError],
    ) -> dict[str, SideRules]:
        """Parse the sides object from a strategy definition."""
        if not isinstance(raw, dict) or not raw:
            errors.append(
                make_error("$.sides", "sides must define at least one of long or short")
            )
            return {}
        aliases = {item.name: item.column_name() for item in indicators}
        sources_map = {
            item.column_name(): item.sources for item in indicators if item.sources
        }
        feature_aliases = {item.name: item.name for item in features}
        return self._parse_side_map(
            raw, aliases, sources_map, feature_aliases, resolved_params, errors
        )

    def _parse_side_map(
        self,
        raw: dict,
        aliases: dict[str, str],
        sources_map: dict[str, list[str]],
        feature_aliases: dict[str, str],
        resolved_params: dict[str, Any],
        errors: list[StrategyValidationError],
    ) -> dict[str, SideRules]:
        sides: dict[str, SideRules] = {}
        for side, spec in raw.items():
            rules = self._parse_side(
                side,
                spec,
                aliases,
                sources_map,
                feature_aliases,
                resolved_params,
                errors,
            )
            if rules is not None:
                sides[side] = rules
        return sides

    def _parse_side(
        self,
        side: str,
        spec: Any,
        aliases: dict[str, str],
        sources_map: dict[str, list[str]],
        feature_aliases: dict[str, str],
        resolved_params: dict[str, Any],
        errors: list[StrategyValidationError],
    ) -> SideRules | None:
        path = f"$.sides.{side}"
        if side not in ("long", "short") or not isinstance(spec, dict):
            errors.append(make_error(path, "side must be long/short object"))
            return None
        entry = self._parse_entry(
            spec,
            aliases,
            sources_map,
            feature_aliases,
            resolved_params,
            path,
            errors,
        )
        if entry is None:
            return None
        exit_group = self._parse_exit_group(
            spec,
            aliases,
            sources_map,
            feature_aliases,
            resolved_params,
            path,
            errors,
        )
        return SideRules(side=side, entry=entry, exit=exit_group)

    def _parse_entry(
        self,
        spec: dict,
        aliases: dict[str, str],
        sources_map: dict[str, list[str]],
        feature_aliases: dict[str, str],
        resolved_params: dict[str, Any],
        path: str,
        errors: list[StrategyValidationError],
    ) -> ConditionGroup | None:
        entry_raw = extract_condition(spec.get("entry"))
        if entry_raw is None:
            errors.append(
                make_error(f"{path}.entry.condition", "entry condition is required")
            )
            return None
        return self._group_parser.parse(
            entry_raw,
            aliases,
            sources_map,
            feature_aliases,
            resolved_params,
            f"{path}.entry.condition",
            errors,
        )

    def _parse_exit_group(
        self,
        spec: dict,
        aliases: dict[str, str],
        sources_map: dict[str, list[str]],
        feature_aliases: dict[str, str],
        resolved_params: dict[str, Any],
        path: str,
        errors: list[StrategyValidationError],
    ) -> ConditionGroup | None:
        exit_raw = extract_condition(spec.get("exit"))
        if exit_raw is None:
            return None
        return self._group_parser.parse(
            exit_raw,
            aliases,
            sources_map,
            feature_aliases,
            resolved_params,
            f"{path}.exit.condition",
            errors,
        )
