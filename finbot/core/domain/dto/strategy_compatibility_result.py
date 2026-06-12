"""Result DTO for strategy compatibility check."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StrategyCompatibilityResult:
    """Reports which strategy features are supported per execution mode."""

    strategy_name: str
    modes: dict[str, dict[str, str]] = field(default_factory=dict)
    """mode -> {feature -> supported|unsupported|planned|error}"""
