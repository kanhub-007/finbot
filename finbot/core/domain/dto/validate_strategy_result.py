"""Result DTO for strategy validation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ValidateStrategyResult:
    """Output from strategy validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    strategy_name: str = ""
    schema_version: str = ""
    primary_timeframe: str = ""
    indicator_count: int = 0
    definition: object | None = None
