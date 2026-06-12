"""StrategyConditionGroupParser — parse nested condition groups."""

from typing import Any

from finbot.core.domain.entities.condition import Condition
from finbot.core.domain.entities.condition_group import ConditionGroup
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)
from finbot.infrastructure.strategy.strategy_definition_parse_helpers import (
    BINARY_OPERATORS,
    UNARY_OPERATORS,
    make_error,
)
from finbot.infrastructure.strategy.strategy_operand_parser import (
    StrategyOperandParser,
)


class StrategyConditionGroupParser:
    """Parse nested all/any/not/atomic condition group objects."""

    def __init__(self, operand_parser: StrategyOperandParser):
        """Create a group parser with an operand parser."""
        self._operand_parser = operand_parser

    def parse(
        self,
        raw: Any,
        aliases: dict[str, str],
        sources_map: dict[str, list[str]],
        feature_aliases: dict[str, str],
        params: dict[str, Any],
        path: str,
        errors: list[StrategyValidationError],
    ) -> ConditionGroup:
        """Parse a condition group from raw JSON data."""
        if not isinstance(raw, dict):
            errors.append(make_error(path, "condition must be an object"))
            return ConditionGroup(kind="all")
        for kind in ("all", "any"):
            if kind in raw:
                return self._parse_children(
                    kind,
                    raw[kind],
                    aliases,
                    sources_map,
                    feature_aliases,
                    params,
                    path,
                    errors,
                )
        if "not" in raw:
            child = self.parse(
                raw["not"],
                aliases,
                sources_map,
                feature_aliases,
                params,
                f"{path}.not",
                errors,
            )
            return ConditionGroup(kind="not", children=[child])
        condition = self._parse_condition(
            raw, aliases, sources_map, feature_aliases, params, path, errors
        )
        return ConditionGroup(kind="condition", condition=condition)

    def _parse_children(
        self,
        kind: str,
        raw_children: Any,
        aliases: dict[str, str],
        sources_map: dict[str, list[str]],
        feature_aliases: dict[str, str],
        params: dict[str, Any],
        path: str,
        errors: list[StrategyValidationError],
    ) -> ConditionGroup:
        if not isinstance(raw_children, list) or not raw_children:
            errors.append(
                make_error(f"{path}.{kind}", f"{kind} must be a non-empty array")
            )
            return ConditionGroup(kind=kind)
        children = [
            self.parse(
                child,
                aliases,
                sources_map,
                feature_aliases,
                params,
                f"{path}.{kind}[{idx}]",
                errors,
            )
            for idx, child in enumerate(raw_children)
        ]
        return ConditionGroup(kind=kind, children=children)

    def _parse_condition(
        self,
        raw: dict,
        aliases: dict[str, str],
        sources_map: dict[str, list[str]],
        feature_aliases: dict[str, str],
        params: dict[str, Any],
        path: str,
        errors: list[StrategyValidationError],
    ) -> Condition:
        operator = str(raw.get("operator", "")).strip()
        if operator not in BINARY_OPERATORS | UNARY_OPERATORS:
            errors.append(
                make_error(f"{path}.operator", f"unsupported operator '{operator}'")
            )
        left = self._operand_parser.parse(
            raw.get("left"),
            aliases,
            sources_map,
            feature_aliases,
            params,
            f"{path}.left",
            errors,
        )
        right = None
        if operator in BINARY_OPERATORS:
            right = self._operand_parser.parse(
                raw.get("right"),
                aliases,
                sources_map,
                feature_aliases,
                params,
                f"{path}.right",
                errors,
            )
        return Condition(left=left, operator=operator, right=right)
