"""Tests for the rule-based strategy evaluator."""

from decimal import Decimal

import pytest

from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.infrastructure.adapters.rule_based_strategy_evaluator import (
    RuleBasedStrategyEvaluator,
)
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)


@pytest.fixture(scope="module")
def amt_def():
    loader = YamlStrategyDefinitionLoader()
    return loader.load_from_file("tests/fixtures/strategies/amt_dip_buyer_final.yaml")


@pytest.fixture(scope="module")
def amt_v2_def():
    loader = YamlStrategyDefinitionLoader()
    return loader.load_from_file("tests/fixtures/strategies/amt_v2_vol_filter.yaml")


def _flat_position() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="BTC", direction=PositionDirection.FLAT, size=Decimal("0")
    )


def _long_position() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="BTC", direction=PositionDirection.LONG, size=Decimal("1")
    )


def _bar(**fields: object) -> dict:
    return dict(fields)


class TestRuleBasedStrategyEvaluator:
    def test_hold_when_no_entry_condition_true(self, amt_def) -> None:
        ev = RuleBasedStrategyEvaluator(
            amt_def, symbol="BTC", interval="1h", strategy_hash="test"
        )
        bar = _bar(
            acceptance_into_value=False,
            above_value=False,
            close=100.0,
        )
        signal = ev.evaluate(bar, _flat_position())
        assert signal.action == SignalAction.HOLD

    def test_long_entry_when_acceptance_into_value_true(self, amt_def) -> None:
        ev = RuleBasedStrategyEvaluator(
            amt_def, symbol="BTC", interval="1h", strategy_hash="test"
        )
        bar = _bar(
            acceptance_into_value=True,
            above_value=False,
            close=100.0,
            atr=2.0,
        )
        signal = ev.evaluate(bar, _flat_position())
        assert signal.action == SignalAction.LONG_ENTRY
        assert signal.symbol == "BTC"
        assert signal.interval == "1h"

    def test_v2_entry_requires_value_area_width_filter(self, amt_v2_def) -> None:
        ev = RuleBasedStrategyEvaluator(
            amt_v2_def,
            symbol="BTC",
            interval="1h",
            strategy_hash="test",
        )
        # Narrow value area + acceptance = entry
        bar = _bar(
            acceptance_into_value=True,
            value_area_width_pct=1.0,  # < 1.5
            close=100.0,
            atr=2.0,
        )
        signal = ev.evaluate(bar, _flat_position())
        assert signal.action == SignalAction.LONG_ENTRY

        # Wide value area blocks entry
        bar2 = _bar(
            acceptance_into_value=True,
            value_area_width_pct=2.0,  # >= 1.5
            close=100.0,
            atr=2.0,
        )
        signal2 = ev.evaluate(bar2, _flat_position())
        assert signal2.action == SignalAction.HOLD

    def test_long_exit_when_above_value_true(self, amt_def) -> None:
        ev = RuleBasedStrategyEvaluator(
            amt_def, symbol="BTC", interval="1h", strategy_hash="test"
        )
        bar = _bar(above_value=True, close=110.0)
        signal = ev.evaluate(bar, _long_position())
        assert signal.action == SignalAction.LONG_EXIT

    def test_entry_signal_includes_stop_and_target(self, amt_def) -> None:
        ev = RuleBasedStrategyEvaluator(
            amt_def, symbol="BTC", interval="1h", strategy_hash="test"
        )
        bar = _bar(
            acceptance_into_value=True,
            above_value=False,
            close=100.0,
            atr=2.0,
        )
        signal = ev.evaluate(bar, _flat_position())
        assert signal.action == SignalAction.LONG_ENTRY
        # Stop: 100 - (2.0 * 3.5) = 93.0
        assert signal.stop_price is not None
        assert float(signal.stop_price) == 93.0
        # Target: 100 + (7.0 * 1.5) = 110.5
        assert signal.target_price is not None
        assert float(signal.target_price) == 110.5

    def test_existing_long_does_not_open_new_long(self, amt_def) -> None:
        ev = RuleBasedStrategyEvaluator(
            amt_def, symbol="BTC", interval="1h", strategy_hash="test"
        )
        bar = _bar(
            acceptance_into_value=True,
            above_value=False,
            close=100.0,
            atr=2.0,
        )
        signal = ev.evaluate(bar, _long_position())
        # Already long — should not produce another long entry.
        assert signal.action != SignalAction.LONG_ENTRY

    def test_evaluator_state_resets_between_replays(self, amt_def) -> None:
        ev = RuleBasedStrategyEvaluator(
            amt_def, symbol="BTC", interval="1h", strategy_hash="test"
        )
        # Run once
        ev.evaluate(
            _bar(acceptance_into_value=True, close=100.0, atr=2.0),
            _flat_position(),
        )
        assert ev._candle_timestamp == 1
        # Reset
        ev.reset()
        assert ev._candle_timestamp == 0
        # Signal after reset should work again
        signal = ev.evaluate(
            _bar(acceptance_into_value=True, close=100.0, atr=2.0),
            _flat_position(),
        )
        assert signal.action == SignalAction.LONG_ENTRY
