"""Tests for the validate-strategy use case."""

from pathlib import Path

from finbot.core.application.use_cases.validate_strategy_definition import (
    ValidateStrategyUseCase,
)
from finbot.core.domain.dto.validate_strategy_request import (
    ValidateStrategyRequest,
)
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "strategies"


def _package_supported_indicators() -> frozenset[str]:
    """Read the package's supported indicator types (data-driven, no drift)."""
    from finbar_strategy_runtime.parser.strategy_capability_service import (
        StrategyCapabilityService,
    )

    caps = StrategyCapabilityService().get_capabilities()["indicators"]
    return frozenset(caps["fixed_indicators"]) | frozenset(caps["period_ranges"])


def _use_case() -> ValidateStrategyUseCase:
    import finbar_strategy_runtime as _rt

    return ValidateStrategyUseCase(
        loader=YamlStrategyDefinitionLoader(),
        supported_indicators=_package_supported_indicators(),
        runtime_package_version=_rt.__version__,
    )


def _read(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class TestValidateStrategyDefinition:
    def test_validate_target_strategies_success(self) -> None:
        uc = _use_case()
        result = uc.validate(
            ValidateStrategyRequest(strategy_content=_read("amt_dip_buyer_final.yaml"))
        )
        assert result.valid is True
        assert result.strategy_name == "amt_dip_buyer_final"

        result2 = uc.validate(
            ValidateStrategyRequest(strategy_content=_read("amt_v2_vol_filter.yaml"))
        )
        assert result2.valid is True

    def test_missing_name_is_error(self) -> None:
        uc = _use_case()
        result = uc.validate(ValidateStrategyRequest(strategy_content="""
                schema_version: "2.0"
                sides:
                  long:
                    entry:
                      condition:
                        operator: is_true
                        left: some_indicator
                """))
        assert result.valid is False
        assert any("name is required" in e for e in result.errors)

    def test_missing_primary_timeframe_is_not_blocking(self) -> None:
        uc = _use_case()
        result = uc.validate(
            ValidateStrategyRequest(strategy_content=_read("amt_dip_buyer_final.yaml"))
        )
        assert result.valid is True
        assert result.primary_timeframe == "1h"

    def test_unknown_operator_is_not_blocking_at_parse(self) -> None:
        """Unknown operators are parsed (schema is flexible) but flagged
        at compatibility-check or evaluation time."""
        uc = _use_case()
        result = uc.validate(
            ValidateStrategyRequest(strategy_content=_read("amt_dip_buyer_final.yaml"))
        )
        assert result.valid is True

    def test_compatibility_output_includes_all_modes(self) -> None:
        uc = _use_case()
        result = uc.compatibility(
            ValidateStrategyRequest(strategy_content=_read("amt_dip_buyer_final.yaml"))
        )
        assert result.strategy_name == "amt_dip_buyer_final"
        for mode in ("replay", "dry_run", "testnet", "live"):
            assert mode in result.modes, f"Missing mode: {mode}"
            assert result.modes[mode].get("parse") == "supported"

    def test_compatibility_reports_stop_loss_support(self) -> None:
        uc = _use_case()
        result = uc.compatibility(
            ValidateStrategyRequest(strategy_content=_read("amt_dip_buyer_final.yaml"))
        )
        for mode_features in result.modes.values():
            assert mode_features.get("stop_loss") == "supported"


class TestPackageCapabilityCompatibility:
    """Compatibility uses package capabilities + Finbot live policy (ADR-3).

    Indicator/operator/schema support comes from the package; Finbot owns
    live-mode policy (e.g. missing stop loss). Schema compatibility is
    explicit and never inferred from package semver.
    """

    def test_compatibility_reports_runtime_package_info(self) -> None:
        uc = _use_case()
        result = uc.compatibility(
            ValidateStrategyRequest(strategy_content=_read("amt_dip_buyer_final.yaml"))
        )
        assert result.runtime_package_name == "finbar-strategy-runtime"
        assert result.runtime_package_version  # non-empty, e.g. "0.1.0"
        assert "2.0" in result.supported_schema_versions

    def test_unsupported_schema_version_rejected_at_parse(self) -> None:
        uc = _use_case()
        result = uc.compatibility(
            ValidateStrategyRequest(
                strategy_content=_read("amt_dip_buyer_final.yaml").replace(
                    'schema_version: "2.0"', 'schema_version: "3.0"'
                )
            )
        )
        for mode_features in result.modes.values():
            assert mode_features.get("parse") == "error"

    def test_unknown_indicator_rejected_with_name(self) -> None:
        uc = _use_case()
        content = """
        schema_version: "2.0"
        name: has_unknown_indicator
        timeframes:
          primary: 1h
        indicators:
          - name: weirdo
            type: totally_unknown_indicator_xyz
        sides:
          long:
            entry:
              condition:
                operator: is_true
                left: weirdo
        risk:
          stop_loss:
            type: atr
            multiplier: 2
        """
        result = uc.compatibility(ValidateStrategyRequest(strategy_content=content))
        # The package parser rejects the unknown indicator and names it.
        for mode_features in result.modes.values():
            assert mode_features.get("parse") == "error"

    def test_supported_indicators_are_data_driven_from_package(self) -> None:
        """An indicator the package catalogues is accepted (no hardcoded list)."""
        supported = _package_supported_indicators()
        # 'sma' is parameterized; 'atr' is fixed. Both come from the package.
        assert "sma" in supported
        assert "atr" in supported
        assert "totally_unknown_indicator_xyz" not in supported

    def test_live_mode_missing_stop_loss_flagged_by_finbot_policy(self) -> None:
        """A valid strategy without a stop loss is flagged in live mode
        (Finbot policy), while still parsing cleanly."""
        uc = _use_case()
        content = """
        schema_version: "2.0"
        name: no_stop_strategy
        timeframes:
          primary: 1h
        indicators:
          - name: atr
            type: atr
        sides:
          long:
            entry:
              condition:
                operator: is_true
                left: atr
        """
        result = uc.compatibility(ValidateStrategyRequest(strategy_content=content))
        # Parses cleanly (package does not require a risk block).
        assert result.modes["replay"].get("parse") == "supported"
        # Finbot live policy flags the missing stop loss.
        assert result.modes["live"].get("stop_loss") == "missing"
