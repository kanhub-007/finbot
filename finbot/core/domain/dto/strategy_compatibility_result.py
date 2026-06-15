"""Result DTO for strategy compatibility check."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StrategyCompatibilityResult:
    """Reports which strategy features are supported per execution mode.

    Also carries the runtime package identity (name/version) and the
    schema versions the installed package supports, for audit and
    diagnostics. Schema compatibility is explicit and never inferred
    from package semver (ADR-3).
    """

    strategy_name: str
    modes: dict[str, dict[str, str]] = field(default_factory=dict)
    """mode -> {feature -> supported|unsupported|planned|error}"""

    runtime_package_name: str = "finbar-strategy-runtime"
    """Name of the shared strategy runtime package."""

    runtime_package_version: str = ""
    """Installed package version (audit/diagnostics only)."""

    supported_schema_versions: frozenset[str] = field(
        default_factory=lambda: frozenset({"2.0"})
    )
    """Strategy schema versions the installed package accepts."""
