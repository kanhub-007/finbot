"""StrategyFeatureResolver — parse derived feature declarations."""

from typing import Any

from finbot.core.domain.entities.feature_spec import FeatureSpec
from finbot.core.domain.entities.indicator_spec import IndicatorSpec
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
from finbot.infrastructure.strategy.strategy_indicator_catalog import (
    StrategyIndicatorCatalog,
)

_ROLLING_TYPES = {"rolling_max", "rolling_min", "rolling_mean", "rolling_std"}
_SIMPLE_TYPES = {"body_pct", "range_pct", "typical_price", "ohlc4"}
_SUPPORTED_TYPES = _ROLLING_TYPES | _SIMPLE_TYPES | {"shift", "formula"}


class StrategyFeatureResolver:
    """Resolve feature declarations to concrete feature specs."""

    def __init__(self, catalog: IndicatorCapabilityProvider | None = None):
        """Create a resolver backed by indicator capabilities."""
        self._catalog = catalog or StrategyIndicatorCatalog()

    def parse(
        self,
        raw: Any,
        indicators: list[IndicatorSpec],
        resolved_params: dict[str, Any],
        errors: list[StrategyValidationError],
    ) -> list[FeatureSpec]:
        """Parse feature declarations from a strategy JSON object."""
        if raw is None:
            return []
        if not isinstance(raw, list):
            errors.append(make_error("$.features", "features must be an array"))
            return []
        features: list[FeatureSpec] = []
        aliases = {item.name: item.column_name() for item in indicators}
        used_names: set[str] = set(aliases)
        for index, item in enumerate(raw):
            self._parse_one(
                index, item, aliases, used_names, resolved_params, features, errors
            )
        return features

    def _parse_one(
        self,
        index: int,
        item: Any,
        aliases: dict[str, str],
        used_names: set[str],
        resolved_params: dict[str, Any],
        features: list[FeatureSpec],
        errors: list[StrategyValidationError],
    ) -> None:
        path = f"$.features[{index}]"
        if not isinstance(item, dict):
            errors.append(make_error(path, "feature spec must be an object"))
            return
        name = str(item.get("name", "")).strip()
        feature_type = str(item.get("type", "")).lower().strip()
        if self._name_invalid(name, used_names, f"{path}.name", errors):
            return
        if feature_type not in _SUPPORTED_TYPES:
            errors.append(
                make_error(f"{path}.type", f"unsupported feature type '{feature_type}'")
            )
            return
        if feature_type == "formula":
            raw_expr = item.get("expression") or item.get("expr")
            if raw_expr is not None:
                raw_expr = _resolve_expr_params(
                    raw_expr,
                    resolved_params,
                    f"{path}.expr",
                    errors,
                )
            features.append(
                FeatureSpec(
                    name=name,
                    type=feature_type,
                    raw_expr=raw_expr,
                )
            )
            used_names.add(name)
            return
        source = self._resolve_source(
            item.get("source", "close"), aliases, f"{path}.source", errors
        )
        window = resolve_expression(
            item.get("window"), resolved_params, f"{path}.window", errors
        )
        shift = resolve_expression(
            item.get("shift", 0), resolved_params, f"{path}.shift", errors
        )
        if self._window_invalid(feature_type, window, f"{path}.window", errors):
            return
        if not isinstance(shift, int) or isinstance(shift, bool) or shift < 0:
            errors.append(
                make_error(f"{path}.shift", "shift must be a non-negative integer")
            )
            return
        features.append(
            FeatureSpec(
                name=name,
                type=feature_type,
                source=source,
                window=window if isinstance(window, int) else None,
                shift=shift,
                raw_window=item.get("window"),
                raw_expr=item.get("expr") if feature_type == "formula" else None,
            )
        )
        used_names.add(name)

    def _name_invalid(
        self,
        name: str,
        used_names: set[str],
        path: str,
        errors: list[StrategyValidationError],
    ) -> bool:
        if not name:
            errors.append(make_error(path, "feature name is required"))
            return True
        if name in used_names or name in OHLCV_FIELDS:
            errors.append(
                make_error(path, "feature name must be unique and not reserved")
            )
            return True
        return False

    def _resolve_source(
        self,
        source: Any,
        aliases: dict[str, str],
        path: str,
        errors: list[StrategyValidationError],
    ) -> str:
        source_name = str(source)
        if source_name in aliases:
            return aliases[source_name]
        if source_name in OHLCV_FIELDS or self._catalog.supports_concrete(source_name):
            return source_name
        errors.append(make_error(path, f"unknown feature source '{source_name}'"))
        return source_name

    def _window_invalid(
        self,
        feature_type: str,
        window: Any,
        path: str,
        errors: list[StrategyValidationError],
    ) -> bool:
        if feature_type not in _ROLLING_TYPES:
            return False
        if not isinstance(window, int) or isinstance(window, bool) or window < 1:
            errors.append(make_error(path, "window must resolve to a positive integer"))
            return True
        return False


def _resolve_expr_params(
    expr: Any,
    resolved_params: dict[str, Any],
    path: str,
    errors: list[StrategyValidationError],
) -> Any:
    """Recursively resolve {{ param }} references in a formula expression tree."""
    if isinstance(expr, dict):
        resolved: dict = {}
        for key, value in expr.items():
            if key == "children":
                resolved[key] = [
                    _resolve_expr_params(child, resolved_params, path, errors)
                    for child in (value if isinstance(value, list) else [])
                ]
            elif key in ("left", "right"):
                resolved[key] = _resolve_leaf(value, resolved_params, path, errors)
            else:
                resolved[key] = value
        return resolved
    return expr


def _resolve_leaf(
    value: Any,
    resolved_params: dict[str, Any],
    path: str,
    errors: list[StrategyValidationError],
) -> Any:
    """Resolve a leaf value, handling {{ param }} string references
    and {"param": "name"} dict references."""
    if isinstance(value, str):
        return resolve_expression(value, resolved_params, path, errors)
    if isinstance(value, dict):
        param_name = value.get("param")
        if param_name is not None and isinstance(param_name, str):
            if param_name not in resolved_params:
                return value
            return resolved_params[param_name]
        return _resolve_expr_params(value, resolved_params, path, errors)
    return value
