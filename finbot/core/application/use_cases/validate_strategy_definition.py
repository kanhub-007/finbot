"""Use case for validating strategy definitions."""

from finbot.core.domain.dto.strategy_compatibility_result import (
    StrategyCompatibilityResult,
)
from finbot.core.domain.dto.validate_strategy_request import (
    ValidateStrategyRequest,
)
from finbot.core.domain.dto.validate_strategy_result import (
    ValidateStrategyResult,
)
from finbot.core.domain.interfaces.strategy_definition_loader import (
    StrategyDefinitionLoader,
)
from finbot.core.domain.interfaces.strategy_validator import StrategyValidator

# Indicators required by the two AMT target strategies.
_KNOWN_INDICATORS = frozenset(
    {
        "atr",
        "vp_vah",
        "vp_val",
        "vp_poc",
        "above_value",
        "below_value",
        "inside_value",
        "acceptance_into_value",
        "value_area_width_pct",
    }
)

# Risk types supported for live execution.
_SUPPORTED_RISK_TYPES = frozenset({"atr", "risk_reward"})

_EXECUTION_MODES = ("replay", "dry_run", "testnet", "live")


class ValidateStrategyUseCase(StrategyValidator):
    """Validate a strategy definition and report compatibility.

    Depends on StrategyDefinitionLoader (domain interface), not on the
    concrete YAML parser. Implements StrategyValidator.
    """

    def __init__(self, loader: StrategyDefinitionLoader):
        self._loader = loader

    def validate(self, request: ValidateStrategyRequest) -> ValidateStrategyResult:
        """Parse and validate a strategy, returning errors/warnings."""
        try:
            definition = self._loader.load_from_text(request.strategy_content)
        except Exception as exc:
            return ValidateStrategyResult(valid=False, errors=[str(exc)])

        return ValidateStrategyResult(
            valid=True,
            strategy_name=definition.name,
            schema_version=definition.schema_version,
            primary_timeframe=(
                definition.timeframes.primary if definition.timeframes else ""
            ),
            indicator_count=len(definition.indicators),
        )

    def compatibility(
        self, request: ValidateStrategyRequest
    ) -> StrategyCompatibilityResult:
        """Check which features are supported in each execution mode."""
        validation = self.validate(request)
        if not validation.valid:
            modes = {m: {"parse": "error"} for m in _EXECUTION_MODES}
            return StrategyCompatibilityResult(
                strategy_name=validation.strategy_name or "invalid",
                modes=modes,
            )

        # Reuse the parsed definition — validate already loaded it, but
        # validate() doesn't return the definition yet. Parse once more
        # until validate() is refactored to return it.
        definition = self._loader.load_from_text(request.strategy_content)
        modes = self._build_compatibility_modes(definition)
        return StrategyCompatibilityResult(strategy_name=definition.name, modes=modes)

    def _build_compatibility_modes(self, definition) -> dict:
        modes: dict[str, dict[str, str]] = {}
        for mode in _EXECUTION_MODES:
            features: dict[str, str] = {"parse": "supported"}
            self._check_indicators(definition, features)
            self._check_risk(definition, features)
            self._check_sides(definition, features, mode)
            modes[mode] = features
        return modes

    def _check_indicators(self, definition, features) -> None:
        unknown: list[str] = []
        for ind in definition.indicators:
            if ind.type not in _KNOWN_INDICATORS:
                unknown.append(ind.type)
        if unknown:
            features["unknown_indicators"] = ", ".join(sorted(set(unknown)))

    def _check_risk(self, definition, features) -> None:
        if definition.risk is None:
            features["stop_loss"] = "missing"
        elif definition.risk.stop_loss_type not in _SUPPORTED_RISK_TYPES:
            features["stop_loss"] = "unsupported"
        else:
            features["stop_loss"] = "supported"

    def _check_sides(self, definition, features, mode) -> None:
        sides = list(definition.sides.keys())
        if "long" in sides:
            features["long_entry"] = "supported"
        if "short" in sides:
            features["short_entry"] = (
                "planned" if mode in ("testnet", "live") else "supported"
            )
