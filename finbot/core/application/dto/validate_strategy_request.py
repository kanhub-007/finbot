"""Request DTO for strategy validation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidateStrategyRequest:
    """Input for validating or checking compatibility of a strategy."""

    strategy_path: str = ""
    strategy_content: str = ""
