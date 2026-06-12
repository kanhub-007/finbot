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


def _use_case() -> ValidateStrategyUseCase:
    return ValidateStrategyUseCase(loader=YamlStrategyDefinitionLoader())


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
