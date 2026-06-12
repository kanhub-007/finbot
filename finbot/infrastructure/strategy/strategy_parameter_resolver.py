"""StrategyParameterResolver — parse and resolve parameters."""

from typing import Any

from finbot.core.domain.entities.strategy_parameter import StrategyParameter
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)
from finbot.infrastructure.strategy.strategy_definition_parse_helpers import (
    PARAMETER_TYPES,
    make_error,
    value_matches_type,
)


class StrategyParameterResolver:
    """Parse parameter declarations and apply runtime overrides."""

    def parse(
        self,
        raw: Any,
        errors: list[StrategyValidationError],
    ) -> dict[str, StrategyParameter]:
        """Parse parameter definitions from a strategy JSON object."""
        if not isinstance(raw, dict):
            errors.append(make_error("$.parameters", "parameters must be an object"))
            return {}
        params: dict[str, StrategyParameter] = {}
        for name, spec in raw.items():
            self._parse_one(name, spec, params, errors)
        return params

    def apply_overrides(
        self,
        params: dict[str, StrategyParameter],
        overrides: dict,
        errors: list[StrategyValidationError],
    ) -> dict[str, Any]:
        """Apply runtime parameter overrides with type and range validation."""
        resolved = {name: param.default for name, param in params.items()}
        for name, value in overrides.items():
            param = params.get(name)
            path = f"$.params.{name}"
            if param is None:
                errors.append(make_error(path, "unknown parameter override"))
                continue
            if self._override_invalid(param, value, path, errors):
                continue
            resolved[name] = value
        return resolved

    def _parse_one(
        self,
        name: str,
        spec: Any,
        params: dict[str, StrategyParameter],
        errors: list[StrategyValidationError],
    ) -> None:
        path = f"$.parameters.{name}"
        if not isinstance(spec, dict):
            errors.append(make_error(path, "parameter spec must be an object"))
            return
        param_type = str(spec.get("type", "")).lower()
        default = spec.get("default")
        if param_type not in PARAMETER_TYPES:
            errors.append(
                make_error(f"{path}.type", "type must be int, float, bool, or string")
            )
            return
        if not value_matches_type(default, param_type):
            errors.append(
                make_error(f"{path}.default", f"default must match type {param_type}")
            )
            return
        minimum = self._parse_bound(spec.get("minimum"), f"{path}.minimum", errors)
        maximum = self._parse_bound(spec.get("maximum"), f"{path}.maximum", errors)
        if self._bounds_invalid(minimum, maximum, path, errors):
            return
        self._validate_range(default, minimum, maximum, f"{path}.default", errors)
        params[name] = StrategyParameter(
            name=name,
            type=param_type,
            default=default,
            minimum=minimum,
            maximum=maximum,
            description=str(spec.get("description", "")),
        )

    def _override_invalid(
        self,
        param: StrategyParameter,
        value: Any,
        path: str,
        errors: list[StrategyValidationError],
    ) -> bool:
        if not value_matches_type(value, param.type):
            errors.append(make_error(path, f"override must match type {param.type}"))
            return True
        before = len(errors)
        self._validate_range(value, param.minimum, param.maximum, path, errors)
        return len(errors) > before

    def _parse_bound(
        self,
        value: Any,
        path: str,
        errors: list[StrategyValidationError],
    ) -> float | None:
        if value is None:
            return None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(
                make_error(path, "bound must be numeric", "invalid_parameter_bound")
            )
            return None
        return float(value)

    def _bounds_invalid(
        self,
        minimum: float | None,
        maximum: float | None,
        path: str,
        errors: list[StrategyValidationError],
    ) -> bool:
        if minimum is None or maximum is None:
            return False
        if minimum <= maximum:
            return False
        errors.append(
            make_error(
                path,
                "minimum must be less than or equal to maximum",
                "invalid_parameter_bound",
            )
        )
        return True

    def _validate_range(
        self,
        value: Any,
        minimum: float | None,
        maximum: float | None,
        path: str,
        errors: list[StrategyValidationError],
    ) -> None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return
        if minimum is not None and value < minimum:
            errors.append(make_error(path, "value is below minimum"))
        if maximum is not None and value > maximum:
            errors.append(make_error(path, "value is above maximum"))
