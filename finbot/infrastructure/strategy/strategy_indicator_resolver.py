"""StrategyIndicatorResolver — resolve indicator aliases."""

from typing import Any

from finbot.core.domain.entities.indicator_spec import IndicatorSpec
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)
from finbot.core.domain.entities.timeframe_declaration import TimeframeDeclaration
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


class StrategyIndicatorResolver:
    """Resolve strategy-local indicator aliases to concrete indicator columns."""

    def __init__(self, catalog: IndicatorCapabilityProvider | None = None):
        """Create a resolver backed by an indicator capability catalog."""
        self._catalog = catalog or StrategyIndicatorCatalog()

    def parse(
        self,
        raw: Any,
        resolved_params: dict[str, Any],
        errors: list[StrategyValidationError],
        timeframes: TimeframeDeclaration | None = None,
    ) -> list[IndicatorSpec]:
        """Parse indicator declarations from a strategy JSON object."""
        if raw is None:
            return []
        if not isinstance(raw, list):
            errors.append(make_error("$.indicators", "indicators must be an array"))
            return []
        indicators: list[IndicatorSpec] = []
        used_aliases: set[str] = set()
        for index, item in enumerate(raw):
            self._parse_one(
                index,
                item,
                resolved_params,
                used_aliases,
                indicators,
                errors,
                timeframes,
            )
        return indicators

    def _parse_one(
        self,
        index: int,
        item: Any,
        resolved_params: dict[str, Any],
        used_aliases: set[str],
        indicators: list[IndicatorSpec],
        errors: list[StrategyValidationError],
        timeframes: TimeframeDeclaration | None,
    ) -> None:
        path = f"$.indicators[{index}]"
        if not isinstance(item, dict):
            errors.append(make_error(path, "indicator spec must be an object"))
            return
        alias = str(item.get("name", "")).strip()
        indicator_type = str(item.get("type", "")).lower().strip()
        if self._alias_invalid(alias, used_aliases, f"{path}.name", errors):
            return
        period = resolve_expression(
            item.get("period"), resolved_params, f"{path}.period", errors
        )
        sources = self._parse_sources(
            indicator_type, item.get("sources"), f"{path}.sources", errors
        )
        if indicator_type == "fallback":
            if not sources:
                return
            concrete = sources[0]
        else:
            if self._period_invalid(
                indicator_type,
                period,
                "period" in item,
                f"{path}.period",
                errors,
            ):
                return
            concrete = self._catalog.resolve(indicator_type, period)
            if concrete is None:
                errors.append(
                    make_error(
                        path,
                        f"unsupported indicator type/period: {indicator_type}_{period}",
                        "unsupported_indicator",
                    )
                )
                return
        timeframe = _resolve_timeframe(
            item.get("timeframe", "primary"), timeframes, f"{path}.timeframe", errors
        )
        if timeframe is None:
            return
        primary_source = sources[0] if sources else concrete
        indicators.append(
            IndicatorSpec(
                name=alias,
                type=indicator_type,
                period=period,
                raw_period=item.get("period"),
                source=str(item.get("source", "close")),
                concrete_name=primary_source,
                expected_column=_expected_column(primary_source, timeframe, timeframes),
                timeframe=timeframe,
                sources=sources[1:] if len(sources) > 1 else sources,
            )
        )
        used_aliases.add(alias)

    def _alias_invalid(
        self,
        alias: str,
        used_aliases: set[str],
        path: str,
        errors: list[StrategyValidationError],
    ) -> bool:
        if not alias:
            errors.append(make_error(path, "indicator name is required"))
            return True
        if alias in used_aliases or alias in OHLCV_FIELDS:
            errors.append(
                make_error(path, "indicator name must be unique and not an OHLCV field")
            )
            return True
        return False

    def _period_invalid(
        self,
        indicator_type: str,
        period: Any,
        period_supplied: bool,
        path: str,
        errors: list[StrategyValidationError],
    ) -> bool:
        if self._catalog.requires_period(indicator_type):
            if not isinstance(period, int) or isinstance(period, bool):
                errors.append(make_error(path, "period must resolve to an integer"))
                return True
            return False
        if period_supplied and period is not None:
            if not self._catalog.accepts_period(indicator_type):
                errors.append(
                    make_error(
                        path,
                        f"indicator type '{indicator_type}' does not support "
                        "custom periods",
                        "unsupported_indicator_parameter",
                    )
                )
                return True
            return False
        return False

    def _parse_sources(
        self,
        indicator_type: str,
        raw: Any,
        path: str,
        errors: list[StrategyValidationError],
    ) -> list[str]:
        """Parse fallback indicator sources."""
        if indicator_type != "fallback":
            if raw is not None:
                errors.append(make_error(path, "sources only valid for fallback type"))
            return []
        if raw is None or not isinstance(raw, list) or len(raw) < 2:
            errors.append(
                make_error(
                    path,
                    "fallback indicators require at least 2 sources",
                )
            )
            return []
        result: list[str] = []
        for idx, source in enumerate(raw):
            if not isinstance(source, str) or not source.strip():
                errors.append(
                    make_error(
                        f"{path}[{idx}]",
                        "each source must be a non-empty string",
                    )
                )
                continue
            name = source.strip()
            if not self._catalog.supports_concrete(name):
                errors.append(
                    make_error(
                        f"{path}[{idx}]",
                        f"unknown concrete indicator '{name}'",
                        "unsupported_indicator",
                    )
                )
            result.append(name)
        return result


def _resolve_timeframe(
    raw: Any,
    timeframes: TimeframeDeclaration | None,
    path: str,
    errors: list[StrategyValidationError],
) -> str | None:
    timeframe = str(raw or "primary").strip()
    if timeframe == "primary":
        return timeframe
    if timeframes is None or timeframes.interval_for(timeframe) is None:
        errors.append(
            make_error(
                path,
                f"unknown timeframe alias '{timeframe}'",
                "unknown_timeframe",
            )
        )
        return None
    return timeframe


def _expected_column(
    concrete: str,
    timeframe: str,
    timeframes: TimeframeDeclaration | None,
) -> str:
    if timeframe == "primary" or timeframes is None:
        return concrete
    interval = timeframes.interval_for(timeframe)
    return f"{concrete}_{interval}" if interval else concrete
