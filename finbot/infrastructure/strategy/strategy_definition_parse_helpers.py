"""Shared helpers for strategy definition parsing."""

import re
from typing import Any

from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)

PARAM_RE = re.compile(r"^\s*\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}\s*$")
OHLCV_FIELDS = {"timestamp", "open", "high", "low", "close", "volume"}
BINARY_OPERATORS = {
    "<",
    ">",
    "<=",
    ">=",
    "==",
    "!=",
    "crosses_above",
    "crosses_below",
    "between",
    "not_between",
}
UNARY_OPERATORS = {"is_true", "is_false", "exists", "missing"}
PARAMETER_TYPES = {"int", "float", "bool", "string"}


def make_error(
    path: str,
    message: str,
    code: str = "validation_error",
) -> StrategyValidationError:
    """Create a path-specific validation error."""
    return StrategyValidationError(path=path, message=message, code=code)


def value_matches_type(value: Any, param_type: str) -> bool:
    """Return True when a value matches a declared strategy parameter type."""
    if param_type == "bool":
        return isinstance(value, bool)
    if param_type == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if param_type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if param_type == "string":
        return isinstance(value, str)
    return False


def extract_condition(raw: Any) -> Any:
    """Extract a condition object from a signal block or raw condition."""
    if isinstance(raw, dict) and "condition" in raw:
        return raw.get("condition")
    return raw


def resolve_expression(
    value: Any,
    resolved_params: dict[str, Any],
    path: str,
    errors: list[StrategyValidationError],
) -> Any:
    """Resolve parameter references inside an arbitrary JSON value."""
    if isinstance(value, list):
        return [
            resolve_expression(item, resolved_params, path, errors) for item in value
        ]
    if isinstance(value, str):
        match = PARAM_RE.match(value)
        if match:
            param_name = match.group(1)
            if param_name not in resolved_params:
                errors.append(
                    make_error(
                        path, f"unknown parameter '{param_name}'", "unknown_parameter"
                    )
                )
                return None
            return resolved_params[param_name]
    return value
