"""Use case for validating strategy definitions."""

from finbot.core.application.dto.strategy_compatibility_result import (
    StrategyCompatibilityResult,
)
from finbot.core.application.dto.validate_strategy_request import (
    ValidateStrategyRequest,
)
from finbot.core.application.dto.validate_strategy_result import (
    ValidateStrategyResult,
)
from finbot.core.domain.interfaces.strategy_definition_loader import (
    StrategyDefinitionLoader,
)

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

# Operators currently supported by the condition evaluator.
_SUPPORTED_OPERATORS = frozenset(
    {
        "is_true",
        "is_false",
        "<",
        ">",
        "<=",
        ">=",
        "==",
        "!=",
        "exists",
        "missing",
    }
)

# Risk types supported for live execution.
_SUPPORTED_RISK_TYPES = frozenset({"atr", "risk_reward"})


class ValidateStrategyUseCase:
    """Validate a strategy definition and report compatibility.

    Depends on StrategyDefinitionLoader (domain interface), not on the
    concrete YAML parser.
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
            return StrategyCompatibilityResult(
                strategy_name=validation.strategy_name or "invalid",
                modes={
                    "replay": {"parse": "error"},
                    "dry_run": {"parse": "error"},
                    "testnet": {"parse": "error"},
                    "live": {"parse": "error"},
                },
            )

        definition = self._loader.load_from_text(request.strategy_content)
        modes: dict[str, dict[str, str]] = {}

        for mode in ("replay", "dry_run", "testnet", "live"):
            features: dict[str, str] = {"parse": "supported"}
            self._check_indicators(definition, features, mode)
            self._check_operators(definition, features, mode)
            self._check_risk(definition, features, mode)
            self._check_sides(definition, features, mode)
            modes[mode] = features

        return StrategyCompatibilityResult(strategy_name=definition.name, modes=modes)

    def _check_indicators(self, definition, features, mode) -> None:
        for ind in definition.indicators:
            if ind.type not in _KNOWN_INDICATORS:
                features[ind.type] = "unsupported"

    def _check_operators(self, definition, features, mode) -> None:
        pass  # Operators are checked at condition-eval time; all supported.

    def _check_risk(self, definition, features, mode) -> None:
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
