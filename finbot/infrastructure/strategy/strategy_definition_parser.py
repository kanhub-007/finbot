"""StrategyDefinitionParser — parse and validate agent JSON strategies."""

from __future__ import annotations

import json

import yaml

from finbot.core.domain.entities.strategy_definition import StrategyDefinition
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)
from finbot.core.domain.entities.strategy_validation_result import (
    StrategyValidationResult,
)
from finbot.core.domain.interfaces.indicator_capability_provider import (
    IndicatorCapabilityProvider,
)
from finbot.core.domain.interfaces.strategy_definition_parser import (
    StrategyDefinitionParser as ParserInterface,
)
from finbot.infrastructure.strategy.required_column_collector import (
    RequiredColumnCollector,
)
from finbot.infrastructure.strategy.strategy_condition_parser import (
    StrategyConditionParser,
)
from finbot.infrastructure.strategy.strategy_definition_serializer import (
    StrategyDefinitionSerializer,
)
from finbot.infrastructure.strategy.strategy_feature_resolver import (
    StrategyFeatureResolver,
)
from finbot.infrastructure.strategy.strategy_indicator_catalog import (
    StrategyIndicatorCatalog,
)
from finbot.infrastructure.strategy.strategy_indicator_resolver import (
    StrategyIndicatorResolver,
)
from finbot.infrastructure.strategy.strategy_limit_rules import (
    DEFAULT_LIMIT_RULES,
    StrategyLimitRule,
)
from finbot.infrastructure.strategy.strategy_parameter_resolver import (
    StrategyParameterResolver,
)
from finbot.infrastructure.strategy.strategy_risk_resolver import (
    StrategyRiskResolver,
)
from finbot.infrastructure.strategy.strategy_timeframe_resolver import (
    StrategyTimeframeResolver,
)
from finbot.infrastructure.strategy.strategy_warning_rules import (
    DEFAULT_WARNING_RULES,
    StrategyWarningRule,
)


class StrategyDefinitionParser(ParserInterface):
    """Parse agent-authored JSON into canonical strategy definitions.

    Warning rules, limit rules, and serializer are injectable for OCP compliance.
    """

    def __init__(
        self,
        catalog: IndicatorCapabilityProvider | None = None,
        warning_rules: list[StrategyWarningRule] | None = None,
        limit_rules: list[StrategyLimitRule] | None = None,
        serializer: StrategyDefinitionSerializer | None = None,
    ):
        """Create a parser with injectable parsing collaborators.

        Args:
            catalog: Indicator capability provider for alias resolution.
            warning_rules: Rules that generate warnings for suspicious strategies.
            limit_rules: Rules that enforce SDK limits.
            serializer: Serializer for canonical dict output.
        """
        self._catalog = catalog or StrategyIndicatorCatalog()
        self._warning_rules = warning_rules or DEFAULT_WARNING_RULES
        self._limit_rules = limit_rules or DEFAULT_LIMIT_RULES
        self._serializer = serializer or StrategyDefinitionSerializer()
        self._parameter_resolver = StrategyParameterResolver()
        self._indicator_resolver = StrategyIndicatorResolver(self._catalog)
        self._feature_resolver = StrategyFeatureResolver(self._catalog)
        self._risk_resolver = StrategyRiskResolver(self._catalog)
        self._timeframe_resolver = StrategyTimeframeResolver()
        self._condition_parser = StrategyConditionParser(self._catalog)

    def parse(
        self,
        raw_definition: str | dict,
        param_overrides: dict | None = None,
    ) -> StrategyValidationResult:
        """Parse, normalize, and validate a strategy definition."""
        errors: list[StrategyValidationError] = []
        data = self._load(raw_definition, errors)
        if data is None:
            return StrategyValidationResult(valid=False, errors=errors)

        name = self._validate_header(data, errors)
        params = self._parameter_resolver.parse(data.get("parameters", {}), errors)
        resolved_params = self._parameter_resolver.apply_overrides(
            params,
            param_overrides or {},
            errors,
        )
        timeframes = self._timeframe_resolver.parse(data.get("timeframes"), errors)
        indicators = self._indicator_resolver.parse(
            data.get("indicators", []),
            resolved_params,
            errors,
            timeframes,
        )
        features = self._feature_resolver.parse(
            data.get("features", []),
            indicators,
            resolved_params,
            errors,
        )
        risk = self._risk_resolver.parse(
            data.get("risk"), indicators, resolved_params, errors
        )
        sides = self._condition_parser.parse_sides(
            data.get("sides"),
            indicators,
            features,
            resolved_params,
            errors,
        )
        if errors:
            return StrategyValidationResult(valid=False, errors=errors)

        definition = StrategyDefinition(
            name=name,
            description=str(data.get("description", "")),
            parameters=params,
            resolved_params=resolved_params,
            indicators=indicators,
            features=features,
            timeframes=timeframes,
            risk=risk,
            sides=sides,
            metadata=_metadata(data),
        )

        warnings = _collect_warnings(definition, self._warning_rules)
        limit_errors = _collect_limit_errors(
            definition, params, indicators, features, self._limit_rules
        )
        errors.extend(limit_errors)
        if errors:
            return StrategyValidationResult(valid=False, errors=errors)

        return StrategyValidationResult(
            valid=True,
            definition=definition,
            normalized=self._serializer.serialize(definition),
            required_indicators=[item.column_name() for item in indicators],
            required_columns=RequiredColumnCollector().collect(definition),
            primary_required_indicators=_primary_required_indicators(indicators),
            informative_required_indicators=_informative_required_indicators(
                indicators
            ),
            timeframe_intervals=_timeframe_intervals(definition),
            warnings=warnings,
        )

    def parse_definition(
        self,
        raw_definition: str | dict,
        param_overrides: dict | None = None,
    ):
        """Parse and return the canonical definition entity directly."""
        result = self.parse(raw_definition, param_overrides)
        return result.definition

    def _load(
        self,
        raw_definition: str | dict,
        errors: list[StrategyValidationError],
    ) -> dict | None:
        if isinstance(raw_definition, dict):
            return raw_definition
        data, parse_error = _parse_any(raw_definition)
        if data is None:
            errors.append(_err("$", parse_error, "invalid_json"))
            return None
        if not isinstance(data, dict):
            errors.append(_err("$", "strategy definition must be a JSON object"))
            return None
        return data

    def _validate_header(
        self,
        data: dict,
        errors: list[StrategyValidationError],
    ) -> str:
        if data.get("schema_version") != "2.0":
            errors.append(_err("$.schema_version", "schema_version must be '2.0'"))
        name = str(data.get("name", "")).strip()
        if not name:
            errors.append(_err("$.name", "name is required"))
        return name


def _metadata(data: dict) -> dict:
    raw = data.get("metadata", {})
    return raw if isinstance(raw, dict) else {}


def _primary_required_indicators(indicators: list) -> list[str]:
    required: list[str] = []
    for item in indicators:
        if item.timeframe == "primary" and item.concrete_name not in required:
            required.append(item.concrete_name)
    return required


def _informative_required_indicators(indicators: list) -> dict[str, list[str]]:
    required: dict[str, list[str]] = {}
    for item in indicators:
        if item.timeframe == "primary":
            continue
        values = required.setdefault(item.timeframe, [])
        if item.concrete_name not in values:
            values.append(item.concrete_name)
    return required


def _timeframe_intervals(definition: StrategyDefinition) -> dict[str, str]:
    if definition.timeframes is None:
        return {}
    intervals = {"primary": definition.timeframes.primary}
    for item in definition.timeframes.informative:
        intervals[item.alias] = item.interval
    return intervals


def _parse_any(raw: str) -> tuple[dict | None, str]:
    """Try JSON first, then YAML. Returns (data, error_message)."""
    try:
        return json.loads(raw), ""
    except json.JSONDecodeError:
        pass
    try:
        data = yaml.safe_load(raw)
        if isinstance(data, dict):
            return data, ""
        return None, "strategy definition must be a JSON or YAML object"
    except yaml.YAMLError as exc:
        return None, f"Invalid JSON or YAML: {exc}"


def _err(
    path: str, message: str, code: str = "validation_error"
) -> StrategyValidationError:
    return StrategyValidationError(path=path, message=message, code=code)


def _collect_warnings(
    definition: StrategyDefinition,
    rules: list[StrategyWarningRule],
) -> list[StrategyValidationError]:
    warnings: list[StrategyValidationError] = []
    for rule in rules:
        warning = rule.check(definition)
        if warning is not None:
            warnings.append(warning)
    return warnings


def _collect_limit_errors(
    definition: StrategyDefinition,
    params: dict,
    indicators: list,
    features: list,
    rules: list[StrategyLimitRule],
) -> list[StrategyValidationError]:
    errors: list[StrategyValidationError] = []
    for rule in rules:
        error = rule.check(definition, params, indicators, features)
        if error is not None:
            errors.append(error)
    return errors
