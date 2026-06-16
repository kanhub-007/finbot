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
from finbot.core.domain.entities.strategy_load_error import StrategyLoadError
from finbot.core.domain.interfaces.strategy_definition_loader import (
    StrategyDefinitionLoader,
)
from finbot.core.domain.interfaces.strategy_validator import StrategyValidator

_EXECUTION_MODES = ("replay", "dry_run", "testnet", "live")


class ValidateStrategyUseCase(StrategyValidator):
    """Validate a strategy definition and report compatibility.

    Indicator/operator/schema/risk support is delegated to the package
    parser (the authority) with injected, package-derived capability sets
    for diagnostics — there are no hand-maintained lists to drift. Finbot
    owns live-mode policy (e.g. "missing stop loss in live mode = reject")
    on top of the package's schema validation.

    Depends on StrategyDefinitionLoader (domain interface), not on the
    concrete YAML parser.
    """

    def __init__(
        self,
        loader: StrategyDefinitionLoader,
        *,
        supported_indicators: frozenset[str] | None = None,
        supported_risk_types: frozenset[str] | None = None,
        supported_schema_versions: frozenset[str] | None = None,
        runtime_package_name: str = "finbar-strategy-runtime",
        runtime_package_version: str = "",
    ):
        self._loader = loader
        self._supported_indicators = supported_indicators
        self._supported_risk_types = supported_risk_types
        self._supported_schema_versions = supported_schema_versions or frozenset(
            {"2.0"}
        )
        self._runtime_package_name = runtime_package_name
        self._runtime_package_version = runtime_package_version

    def validate(self, request: ValidateStrategyRequest) -> ValidateStrategyResult:
        """Parse and validate a strategy, returning errors/warnings."""
        try:
            definition = self._loader.load_from_text(request.strategy_content)
        except StrategyLoadError as exc:
            return ValidateStrategyResult(valid=False, errors=[str(exc)])
        except Exception as exc:
            return ValidateStrategyResult(valid=False, errors=[str(exc)])

        return ValidateStrategyResult(
            valid=True,
            definition=definition,
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
            return self._result(validation.strategy_name or "invalid", modes)

        # definition was already parsed by validate() above.
        definition = validation.definition
        if definition is None:
            modes = {m: {"parse": "error"} for m in _EXECUTION_MODES}
            return self._result(validation.strategy_name or "invalid", modes)

        modes = self._build_compatibility_modes(definition)
        return self._result(definition.name, modes)

    def _result(self, name: str, modes: dict) -> StrategyCompatibilityResult:
        """Build a compatibility result carrying runtime package identity."""
        return StrategyCompatibilityResult(
            strategy_name=name,
            modes=modes,
            runtime_package_name=self._runtime_package_name,
            runtime_package_version=self._runtime_package_version,
            supported_schema_versions=self._supported_schema_versions,
        )

    def _build_compatibility_modes(self, definition) -> dict:
        modes: dict[str, dict[str, str]] = {}
        for mode in _EXECUTION_MODES:
            features: dict[str, str] = {"parse": "supported"}
            self._check_schema(definition, features)
            self._check_indicators(definition, features)
            self._check_risk(definition, features)
            self._check_sides(definition, features, mode)
            modes[mode] = features
        return modes

    def _check_schema(self, definition, features) -> None:
        """Flag schema versions the installed package does not accept."""
        if definition.schema_version not in self._supported_schema_versions:
            features["schema_version"] = "unsupported"

    def _check_indicators(self, definition, features) -> None:
        """Flag indicator types not in the package-derived supported set.

        The package parser is the authority and already rejects unknown
        indicators at parse time, so this only runs on valid strategies.
        When no supported set is injected, this check is skipped (the
        parser has already enforced it).
        """
        if self._supported_indicators is None:
            return
        unknown: list[str] = []
        for ind in definition.indicators:
            if ind.type not in self._supported_indicators:
                unknown.append(ind.type)
        if unknown:
            features["unknown_indicators"] = ", ".join(sorted(set(unknown)))

    def _check_risk(self, definition, features) -> None:
        if definition.risk is None or definition.risk.stop_loss_type == "none":
            features["stop_loss"] = "missing"
        elif (
            self._supported_risk_types is not None
            and definition.risk.stop_loss_type not in self._supported_risk_types
        ):
            features["stop_loss"] = "unsupported"
        else:
            features["stop_loss"] = "supported"

    def _check_sides(self, definition, features, mode) -> None:
        sides = list(definition.sides.keys())
        if "long" in sides:
            features["long_entry"] = "supported"
        if "short" in sides:
            features["short_entry"] = "supported"
