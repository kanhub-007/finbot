"""Tests for the YAML strategy definition loader."""

from pathlib import Path

import pytest
from finbar_strategy_runtime.domain.entities.strategy_definition import (
    StrategyDefinition,
)

from finbot.core.domain.entities.strategy_load_error import StrategyLoadError
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "strategies"


def _loader() -> YamlStrategyDefinitionLoader:
    return YamlStrategyDefinitionLoader()


@pytest.fixture(scope="module")
def amt_dip_buyer() -> StrategyDefinition:
    return _loader().load_from_file(str(FIXTURES_DIR / "amt_dip_buyer_final.yaml"))


@pytest.fixture(scope="module")
def amt_v2() -> StrategyDefinition:
    return _loader().load_from_file(str(FIXTURES_DIR / "amt_v2_vol_filter.yaml"))


class TestYamlStrategyDefinitionLoader:
    def test_load_amt_dip_buyer_final(self, amt_dip_buyer: StrategyDefinition) -> None:
        assert amt_dip_buyer.name == "amt_dip_buyer_final"
        assert amt_dip_buyer.schema_version == "2.0"

    def test_load_amt_v2_vol_filter(self, amt_v2: StrategyDefinition) -> None:
        assert amt_v2.name == "amt_v2_vol_filter"
        assert amt_v2.schema_version == "2.0"

    def test_load_strategy_parameters(self, amt_dip_buyer: StrategyDefinition) -> None:
        assert "atr_stop_mult" in amt_dip_buyer.parameters
        param = amt_dip_buyer.parameters["atr_stop_mult"]
        assert param.type == "float"
        assert param.default == 3.5

    def test_load_primary_timeframe(self, amt_dip_buyer: StrategyDefinition) -> None:
        assert amt_dip_buyer.timeframes is not None
        assert amt_dip_buyer.timeframes.primary == "1h"

    def test_load_indicators_in_order(self, amt_dip_buyer: StrategyDefinition) -> None:
        indicator_types = [ind.type for ind in amt_dip_buyer.indicators]
        assert "atr" in indicator_types
        assert "vp_vah" in indicator_types
        assert "vp_val" in indicator_types
        assert "above_value" in indicator_types
        assert "acceptance_into_value" in indicator_types

    def test_load_long_entry_and_exit_conditions(
        self, amt_dip_buyer: StrategyDefinition
    ) -> None:
        assert "long" in amt_dip_buyer.sides
        long_side = amt_dip_buyer.sides["long"]
        assert long_side.entry is not None
        assert long_side.exit is not None

    def test_load_risk_block(self, amt_dip_buyer: StrategyDefinition) -> None:
        assert amt_dip_buyer.risk is not None
        assert amt_dip_buyer.risk.stop_loss_type == "atr"
        assert amt_dip_buyer.risk.take_profit_type == "risk_reward"
        assert amt_dip_buyer.risk.risk_reward_ratio == 1.5

    def test_missing_file_returns_clear_error(self) -> None:
        loader = _loader()
        with pytest.raises(FileNotFoundError):
            loader.load_from_file("nonexistent_strategy.yaml")

    def test_invalid_yaml_returns_clear_error(self) -> None:
        loader = _loader()
        with pytest.raises(StrategyLoadError, match="Strategy validation failed"):
            loader.load_from_text("not: valid: yaml: [")

    def test_schema_validation_rejects_missing_name(self) -> None:
        loader = _loader()
        with pytest.raises(StrategyLoadError, match="name is required"):
            loader.load_from_text("""
                schema_version: "2.0"
                sides:
                  long:
                    entry:
                      condition:
                        operator: is_true
                        left: some_indicator
                """)

    def test_v2_strategy_loads_value_area_width_filter(
        self, amt_v2: StrategyDefinition
    ) -> None:
        indicator_types = [ind.type for ind in amt_v2.indicators]
        assert "value_area_width_pct" in indicator_types

    def test_path_traversal_is_rejected(self) -> None:
        loader = _loader()
        with pytest.raises(FileNotFoundError):
            loader.load_from_file("../../../etc/passwd")


class TestLoaderSurfacesPackageRequiredColumns:
    """The loader must surface the package validation result's
    required_columns so the runtime/enrichment validator read the
    *concrete, directly-referenced* columns, not the strategy-local
    aliases.

    Note: the package's RequiredColumnCollector returns OHLCV plus the
    columns referenced directly in condition trees / risk stops. For the
    AMT strategy, vp_vah/vp_val are intermediate (only used to compute
    the composite above_value/acceptance_into_value indicators), so they
    are intentionally NOT in required_columns — the validator only needs
    the final, directly-evaluated columns.
    """

    def test_last_required_columns_contains_concrete_referenced_names(self) -> None:
        loader = _loader()
        loader.load_from_file(str(FIXTURES_DIR / "amt_dip_buyer_final.yaml"))

        columns = loader.last_required_columns()
        # Directly-referenced concrete indicator columns + engine OHLCV.
        assert "atr" in columns
        assert "above_value" in columns
        assert "acceptance_into_value" in columns
        assert "open" in columns and "close" in columns

    def test_last_required_columns_empty_before_any_load(self) -> None:
        assert _loader().last_required_columns() == []

    def test_required_columns_survive_round_trip_as_list(self) -> None:
        loader = _loader()
        loader.load_from_file(str(FIXTURES_DIR / "amt_v2_vol_filter.yaml"))

        columns = loader.last_required_columns()
        assert isinstance(columns, list)
        assert "value_area_width_pct" in columns


class TestRequiredColumnsAreConcreteNotAliases:
    """Required columns must be the package's CONCRETE column names, not the
    strategy-local indicator aliases.

    This is the bug the migration fixes: the old factory derived required
    columns as ``{ind.name for ind in definition.indicators}`` (the alias).
    For a dynamic-period indicator the alias (``my_sma``) differs from the
    concrete computed column (``sma_37``), so the old derivation pointed the
    enrichment validator at a column that never exists on the frame.
    """

    def test_dynamic_period_indicator_yields_concrete_column(self) -> None:
        loader = _loader()
        definition = loader.load_from_file(str(FIXTURES_DIR / "dyn_sma_cross.yaml"))
        columns = loader.last_required_columns()

        # The alias is ``my_sma``; the concrete computed column is ``sma_37``.
        assert "sma_37" in columns
        assert "my_sma" not in columns
        # Sanity: the alias is indeed what the old derivation would have used.
        assert any(ind.name == "my_sma" for ind in definition.indicators)

    def test_adding_an_indicator_appears_in_required_columns(self) -> None:
        """A newly-referenced indicator surfaces in required_columns automatically."""
        loader = _loader()
        loader.load_from_file(str(FIXTURES_DIR / "dyn_sma_cross.yaml"))

        # Add an EMA indicator AND reference it in the entry condition.
        with open(FIXTURES_DIR / "dyn_sma_cross.yaml", encoding="utf-8") as f:
            base = f.read()
        amended = base.replace(
            '  - name: my_sma\n    type: sma\n    period: "{{ sma_period }}"',
            '  - name: my_sma\n    type: sma\n    period: "{{ sma_period }}"\n'
            '  - name: trend\n    type: ema\n    period: "{{ sma_period }}"',
        ).replace(
            '        operator: ">"\n        left: close\n        right: my_sma',
            '        operator: ">"\n        left: close\n        right: trend',
        )
        loader.load_from_text(amended)
        after = set(loader.last_required_columns())

        # The newly-referenced EMA's concrete column appears; the now-unreferenced
        # SMA concrete column drops out (it was only referenced before).
        assert "ema_37" in after
        assert "sma_37" not in after
