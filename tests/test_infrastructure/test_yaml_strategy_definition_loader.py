"""Tests for the YAML strategy definition loader."""

from pathlib import Path

import pytest

from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "strategies"


def _loader() -> YamlStrategyDefinitionLoader:
    return YamlStrategyDefinitionLoader()


class TestYamlStrategyDefinitionLoader:
    def test_load_amt_dip_buyer_final(self) -> None:
        loader = _loader()
        definition = loader.load_from_file(
            str(FIXTURES_DIR / "amt_dip_buyer_final.yaml")
        )
        assert definition.name == "amt_dip_buyer_final"
        assert definition.schema_version == "2.0"

    def test_load_amt_v2_vol_filter(self) -> None:
        loader = _loader()
        definition = loader.load_from_file(str(FIXTURES_DIR / "amt_v2_vol_filter.yaml"))
        assert definition.name == "amt_v2_vol_filter"
        assert definition.schema_version == "2.0"

    def test_load_strategy_parameters(self) -> None:
        loader = _loader()
        definition = loader.load_from_file(
            str(FIXTURES_DIR / "amt_dip_buyer_final.yaml")
        )
        assert "atr_stop_mult" in definition.parameters
        param = definition.parameters["atr_stop_mult"]
        assert param.type == "float"
        assert param.default == 3.5

    def test_load_primary_timeframe(self) -> None:
        loader = _loader()
        definition = loader.load_from_file(
            str(FIXTURES_DIR / "amt_dip_buyer_final.yaml")
        )
        assert definition.timeframes is not None
        assert definition.timeframes.primary == "1h"

    def test_load_indicators_in_order(self) -> None:
        loader = _loader()
        definition = loader.load_from_file(
            str(FIXTURES_DIR / "amt_dip_buyer_final.yaml")
        )
        indicator_types = [ind.type for ind in definition.indicators]
        assert "atr" in indicator_types
        assert "vp_vah" in indicator_types
        assert "vp_val" in indicator_types
        assert "above_value" in indicator_types
        assert "acceptance_into_value" in indicator_types

    def test_load_long_entry_and_exit_conditions(self) -> None:
        loader = _loader()
        definition = loader.load_from_file(
            str(FIXTURES_DIR / "amt_dip_buyer_final.yaml")
        )
        assert "long" in definition.sides
        long_side = definition.sides["long"]
        assert long_side.entry is not None
        assert long_side.exit is not None

    def test_load_risk_block(self) -> None:
        loader = _loader()
        definition = loader.load_from_file(
            str(FIXTURES_DIR / "amt_dip_buyer_final.yaml")
        )
        assert definition.risk is not None
        assert definition.risk.stop_loss_type == "atr"
        assert definition.risk.take_profit_type == "risk_reward"
        assert definition.risk.risk_reward_ratio == 1.5

    def test_missing_file_returns_clear_error(self) -> None:
        loader = _loader()
        with pytest.raises(FileNotFoundError):
            loader.load_from_file("nonexistent_strategy.yaml")

    def test_invalid_yaml_returns_clear_error(self) -> None:
        loader = _loader()
        with pytest.raises(ValueError, match="Strategy validation failed"):
            loader.load_from_text("not: valid: yaml: [")

    def test_v2_strategy_loads_value_area_width_filter(self) -> None:
        loader = _loader()
        definition = loader.load_from_file(str(FIXTURES_DIR / "amt_v2_vol_filter.yaml"))
        indicator_types = [ind.type for ind in definition.indicators]
        assert "value_area_width_pct" in indicator_types
