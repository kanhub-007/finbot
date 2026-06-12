"""StrategyTimeframeResolver — parse multi-timeframe declarations."""

from typing import Any

from finbot.core.domain.entities.informative_timeframe import InformativeTimeframe
from finbot.core.domain.entities.interval import Interval
from finbot.core.domain.entities.strategy_validation_error import (
    StrategyValidationError,
)
from finbot.core.domain.entities.timeframe_declaration import TimeframeDeclaration
from finbot.infrastructure.strategy.strategy_definition_parse_helpers import (
    OHLCV_FIELDS,
    make_error,
)

_MAX_INFORMATIVE_TIMEFRAMES = 3


class StrategyTimeframeResolver:
    """Parse and validate optional strategy timeframe declarations."""

    def parse(
        self,
        raw: Any,
        errors: list[StrategyValidationError],
    ) -> TimeframeDeclaration | None:
        """Parse the optional timeframes block."""
        if raw in (None, {}):
            return None
        if not isinstance(raw, dict):
            errors.append(make_error("$.timeframes", "timeframes must be an object"))
            return None
        primary = str(raw.get("primary", "")).strip()
        self._validate_interval(primary, "$.timeframes.primary", errors)
        informative = self._parse_informative(raw.get("informative", []), errors)
        return TimeframeDeclaration(primary=primary, informative=informative)

    def _parse_informative(
        self,
        raw: Any,
        errors: list[StrategyValidationError],
    ) -> list[InformativeTimeframe]:
        if raw in (None, []):
            return []
        if not isinstance(raw, list):
            errors.append(
                make_error("$.timeframes.informative", "informative must be an array")
            )
            return []
        if len(raw) > _MAX_INFORMATIVE_TIMEFRAMES:
            errors.append(
                make_error(
                    "$.timeframes.informative",
                    "at most 3 informative timeframes are supported",
                    "timeframe_limit_exceeded",
                )
            )
        return self._parse_informative_items(raw, errors)

    def _parse_informative_items(
        self,
        raw: list,
        errors: list[StrategyValidationError],
    ) -> list[InformativeTimeframe]:
        items: list[InformativeTimeframe] = []
        aliases: set[str] = set()
        intervals: set[str] = set()
        for index, item in enumerate(raw):
            path = f"$.timeframes.informative[{index}]"
            parsed = self._parse_one_informative(item, path, aliases, intervals, errors)
            if parsed is not None:
                items.append(parsed)
        return items

    def _parse_one_informative(
        self,
        raw: Any,
        path: str,
        aliases: set[str],
        intervals: set[str],
        errors: list[StrategyValidationError],
    ) -> InformativeTimeframe | None:
        if not isinstance(raw, dict):
            errors.append(make_error(path, "informative timeframe must be an object"))
            return None
        alias = str(raw.get("alias", "")).strip()
        interval = str(raw.get("interval", "")).strip()
        if self._alias_invalid(alias, aliases, f"{path}.alias", errors):
            return None
        if self._interval_invalid(interval, intervals, f"{path}.interval", errors):
            return None
        if self._validate_interval(interval, f"{path}.interval", errors):
            aliases.add(alias)
            intervals.add(interval)
            return InformativeTimeframe(alias=alias, interval=interval)
        return None

    def _alias_invalid(
        self,
        alias: str,
        aliases: set[str],
        path: str,
        errors: list[StrategyValidationError],
    ) -> bool:
        if not alias:
            errors.append(make_error(path, "timeframe alias is required"))
            return True
        if alias == "primary" or alias in aliases or alias in OHLCV_FIELDS:
            errors.append(
                make_error(
                    path,
                    "timeframe alias must be unique and not reserved",
                    "invalid_timeframe_alias",
                )
            )
            return True
        return False

    def _interval_invalid(
        self,
        interval: str,
        intervals: set[str],
        path: str,
        errors: list[StrategyValidationError],
    ) -> bool:
        if interval in intervals:
            errors.append(
                make_error(
                    path,
                    "informative intervals must be unique to avoid column collisions",
                    "duplicate_timeframe_interval",
                )
            )
            return True
        return False

    def _validate_interval(
        self,
        interval: str,
        path: str,
        errors: list[StrategyValidationError],
    ) -> bool:
        if not interval:
            errors.append(make_error(path, "interval is required"))
            return False
        try:
            Interval(interval)
            return True
        except ValueError:
            allowed = ", ".join(item.value for item in Interval)
            errors.append(
                make_error(
                    path,
                    f"unknown interval '{interval}'. Allowed: {allowed}",
                    "unknown_interval",
                )
            )
            return False
