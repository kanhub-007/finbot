"""Tests for the package-backed strategy evaluator and its factory.

These tests exercise the adapter that wraps a package
``TradingStrategy`` and emits a Finbot ``SignalDecision``. They are
black-box: they assert on the returned ``SignalDecision`` outcomes,
never on which internal methods were called. The fixture strategies
are loaded through Finbot's own ``YamlStrategyDefinitionLoader`` so the
adapter is exercised against real parsed definitions.
"""

from decimal import Decimal

import pytest

from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.position_snapshot import PositionSnapshot
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator
from finbot.infrastructure.adapters.shared_runtime_strategy_evaluator_factory import (
    SharedRuntimeStrategyEvaluatorFactory,
)
from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
    YamlStrategyDefinitionLoader,
)

AMT_DIP = "tests/fixtures/strategies/amt_dip_buyer_final.yaml"


@pytest.fixture(scope="module")
def amt_def():
    """Load the AMT dip buyer fixture once for the whole module."""
    return YamlStrategyDefinitionLoader().load_from_file(AMT_DIP)


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


class TestSharedRuntimeStrategyEvaluatorFactory:
    def test_factory_creates_a_strategy_evaluator(self, amt_def) -> None:
        factory = SharedRuntimeStrategyEvaluatorFactory()

        evaluator = factory.create(
            amt_def, symbol="BTC", interval="1h", strategy_hash="abc"
        )

        assert isinstance(evaluator, StrategyEvaluator)

    def test_triggered_bar_produces_entry_signal_with_context(
        self, amt_def
    ) -> None:
        factory = SharedRuntimeStrategyEvaluatorFactory()
        evaluator = factory.create(
            amt_def, symbol="BTC", interval="1h", strategy_hash="abc"
        )

        bar = _bar(
            acceptance_into_value=True,
            above_value=False,
            close=100.0,
            atr=2.0,
        )
        decision = evaluator.evaluate(bar, _flat_position())

        assert isinstance(decision, SignalDecision)
        assert decision.action.value in {"long_entry", "short_entry"}
        assert decision.symbol == "BTC"
        assert decision.interval == "1h"
        assert decision.strategy_hash == "abc"

    def test_hold_bar_produces_hold_with_populated_signal_key(
        self, amt_def
    ) -> None:
        factory = SharedRuntimeStrategyEvaluatorFactory()
        evaluator = factory.create(
            amt_def, symbol="BTC", interval="1h", strategy_hash="abc"
        )

        bar = _bar(
            acceptance_into_value=False,
            above_value=False,
            close=100.0,
        )
        decision = evaluator.evaluate(bar, _flat_position())

        assert decision.action == SignalAction.HOLD
        # signal_key carries symbol/interval/candle_timestamp/hash for idempotency.
        assert decision.signal_key

    def test_exit_signal_uses_current_position_direction(self, amt_def) -> None:
        """An exit while long must resolve to LONG_EXIT, not SHORT_EXIT."""
        factory = SharedRuntimeStrategyEvaluatorFactory()
        evaluator = factory.create(
            amt_def, symbol="BTC", interval="1h", strategy_hash="abc"
        )

        bar = _bar(above_value=True, close=110.0)
        decision = evaluator.evaluate(bar, _long_position())

        assert decision.action == SignalAction.LONG_EXIT

    def test_entry_signal_includes_stop_and_target(self, amt_def) -> None:
        factory = SharedRuntimeStrategyEvaluatorFactory()
        evaluator = factory.create(
            amt_def, symbol="BTC", interval="1h", strategy_hash="abc"
        )

        bar = _bar(
            acceptance_into_value=True,
            above_value=False,
            close=100.0,
            atr=2.0,
        )
        decision = evaluator.evaluate(bar, _flat_position())

        # Stop: 100 - (2.0 * 3.5) = 93.0 ; Target: 100 + (7.0 * 1.5) = 110.5
        assert decision.action == SignalAction.LONG_ENTRY
        assert decision.stop_price is not None
        assert float(decision.stop_price) == pytest.approx(93.0)
        assert decision.target_price is not None
        assert float(decision.target_price) == pytest.approx(110.5)

    def test_reset_resets_crossover_state(self, amt_def) -> None:
        factory = SharedRuntimeStrategyEvaluatorFactory()
        evaluator = factory.create(
            amt_def, symbol="BTC", interval="1h", strategy_hash="abc"
        )

        evaluator.evaluate(
            _bar(acceptance_into_value=True, close=100.0, atr=2.0),
            _flat_position(),
        )
        # Should not raise; state resets cleanly for a new run.
        evaluator.reset()

        decision = evaluator.evaluate(
            _bar(acceptance_into_value=True, close=100.0, atr=2.0),
            _flat_position(),
        )
        assert decision.action == SignalAction.LONG_ENTRY
