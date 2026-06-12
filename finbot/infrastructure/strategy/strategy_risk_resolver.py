"""StrategyRiskResolver — parse structured risk blocks."""

from typing import Any

from finbot.core.domain.entities.indicator_spec import IndicatorSpec
from finbot.core.domain.entities.risk_spec import RiskSpec
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)
from finbot.core.domain.interfaces.indicator_capability_provider import (
    IndicatorCapabilityProvider,
)
from finbot.infrastructure.strategy.strategy_definition_parse_helpers import (
    make_error,
    resolve_expression,
)
from finbot.infrastructure.strategy.strategy_indicator_catalog import (
    StrategyIndicatorCatalog,
)

_STOP_TYPES = {"none", "atr", "fixed_pct"}
_TAKE_PROFIT_TYPES = {"none", "atr", "fixed_pct", "risk_reward"}


class StrategyRiskResolver:
    """Parse structured risk settings for JSON strategies."""

    def __init__(self, catalog: IndicatorCapabilityProvider | None = None):
        """Create a resolver backed by indicator capabilities."""
        self._catalog = catalog or StrategyIndicatorCatalog()

    def parse(
        self,
        raw: Any,
        indicators: list[IndicatorSpec],
        resolved_params: dict[str, Any],
        errors: list[StrategyValidationError],
    ) -> RiskSpec | None:
        """Parse the optional risk block."""
        if raw in (None, {}):
            return None
        if not isinstance(raw, dict):
            errors.append(make_error("$.risk", "risk must be an object"))
            return None
        stop = _risk_section(raw, "stop_loss", errors)
        target = _risk_section(raw, "take_profit", errors)
        if stop is None or target is None:
            return None
        aliases = {item.name: item.column_name() for item in indicators}
        spec = self._build_spec(stop, target, aliases, resolved_params, errors)
        _validate_required_values(spec, errors)
        return spec

    def _build_spec(
        self,
        stop: dict,
        target: dict,
        aliases: dict[str, str],
        resolved_params: dict[str, Any],
        errors: list[StrategyValidationError],
    ) -> RiskSpec:
        stop_type = str(stop.get("type", "none")).lower()
        target_type = str(target.get("type", "none")).lower()
        _validate_types(stop_type, target_type, errors)
        return RiskSpec(
            stop_loss_type=stop_type,
            stop_indicator=self._resolve_atr_indicator(
                stop_type,
                stop.get("indicator", "atr"),
                aliases,
                "$.risk.stop_loss.indicator",
                errors,
            ),
            stop_multiplier=_positive_float(
                resolve_expression(
                    stop.get("multiplier", 0),
                    resolved_params,
                    "$.risk.stop_loss.multiplier",
                    errors,
                ),
                "$.risk.stop_loss.multiplier",
                errors,
            ),
            stop_pct=_positive_float(
                resolve_expression(
                    stop.get("pct", 0),
                    resolved_params,
                    "$.risk.stop_loss.pct",
                    errors,
                ),
                "$.risk.stop_loss.pct",
                errors,
            ),
            take_profit_type=target_type,
            take_profit_indicator=self._resolve_atr_indicator(
                target_type,
                target.get("indicator", "atr"),
                aliases,
                "$.risk.take_profit.indicator",
                errors,
            ),
            take_profit_multiplier=_positive_float(
                resolve_expression(
                    target.get("multiplier", 0),
                    resolved_params,
                    "$.risk.take_profit.multiplier",
                    errors,
                ),
                "$.risk.take_profit.multiplier",
                errors,
            ),
            take_profit_pct=_positive_float(
                resolve_expression(
                    target.get("pct", 0),
                    resolved_params,
                    "$.risk.take_profit.pct",
                    errors,
                ),
                "$.risk.take_profit.pct",
                errors,
            ),
            risk_reward_ratio=_positive_float(
                resolve_expression(
                    target.get("ratio", 0),
                    resolved_params,
                    "$.risk.take_profit.ratio",
                    errors,
                ),
                "$.risk.take_profit.ratio",
                errors,
            ),
        )

    def _resolve_atr_indicator(
        self,
        risk_type: str,
        raw: Any,
        aliases: dict[str, str],
        path: str,
        errors: list[StrategyValidationError],
    ) -> str:
        name = str(raw)
        if risk_type != "atr":
            return name
        if name in aliases:
            return aliases[name]
        if self._catalog.supports_concrete(name):
            return name
        errors.append(
            make_error(
                path, f"Unknown risk indicator '{name}'", "unknown_risk_indicator"
            )
        )
        return name


def _risk_section(
    raw: dict,
    name: str,
    errors: list[StrategyValidationError],
) -> dict | None:
    section = raw.get(name, {"type": "none"})
    if isinstance(section, dict):
        return section
    errors.append(make_error(f"$.risk.{name}", f"{name} must be an object"))
    return None


def _validate_types(
    stop_type: str,
    target_type: str,
    errors: list[StrategyValidationError],
) -> None:
    if stop_type not in _STOP_TYPES:
        errors.append(make_error("$.risk.stop_loss.type", "unsupported stop type"))
    if target_type not in _TAKE_PROFIT_TYPES:
        errors.append(
            make_error("$.risk.take_profit.type", "unsupported take-profit type")
        )


def _positive_float(
    raw: Any,
    path: str,
    errors: list[StrategyValidationError],
) -> float:
    if raw in (None, ""):
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        errors.append(
            make_error(path, "value must be numeric", "invalid_risk_parameter")
        )
        return 0.0
    if value < 0:
        errors.append(
            make_error(path, "value must be non-negative", "invalid_risk_parameter")
        )
        return 0.0
    return value


def _validate_required_values(
    spec: RiskSpec,
    errors: list[StrategyValidationError],
) -> None:
    _require_positive(
        spec.stop_loss_type == "atr",
        spec.stop_multiplier,
        "$.risk.stop_loss.multiplier",
        errors,
    )
    _require_positive(
        spec.stop_loss_type == "fixed_pct",
        spec.stop_pct,
        "$.risk.stop_loss.pct",
        errors,
    )
    _require_positive(
        spec.take_profit_type == "atr",
        spec.take_profit_multiplier,
        "$.risk.take_profit.multiplier",
        errors,
    )
    _require_positive(
        spec.take_profit_type == "fixed_pct",
        spec.take_profit_pct,
        "$.risk.take_profit.pct",
        errors,
    )
    _require_positive(
        spec.take_profit_type == "risk_reward",
        spec.risk_reward_ratio,
        "$.risk.take_profit.ratio",
        errors,
    )


def _require_positive(
    applies: bool,
    value: float,
    path: str,
    errors: list[StrategyValidationError],
) -> None:
    if applies and value <= 0:
        errors.append(
            make_error(
                path, "value must be greater than zero", "invalid_risk_parameter"
            )
        )
