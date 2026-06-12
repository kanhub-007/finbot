"""Tests for SafetyValidation result type and domain entities."""

import pytest

from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.core.domain.entities.safety_validation import SafetyValidation
from finbot.core.domain.entities.signal_action import SignalAction
from finbot.core.domain.entities.signal_decision import SignalDecision


class TestSafetyValidation:
    def test_success_is_valid_with_no_errors(self) -> None:
        result = SafetyValidation.success()
        assert result.is_valid is True
        assert result.errors == ()

    def test_failure_is_invalid_with_errors(self) -> None:
        result = SafetyValidation.failure("error one", "error two")
        assert result.is_valid is False
        assert result.errors == ("error one", "error two")

    def test_failure_requires_at_least_one_error(self) -> None:
        with pytest.raises(ValueError, match="at least one error"):
            SafetyValidation.failure()

    def test_merge_two_valid_is_valid(self) -> None:
        a = SafetyValidation.success()
        b = SafetyValidation.success()
        merged = a.merge(b)
        assert merged.is_valid is True
        assert merged.errors == ()

    def test_merge_valid_and_invalid_is_invalid(self) -> None:
        a = SafetyValidation.success()
        b = SafetyValidation.failure("b failed")
        merged = a.merge(b)
        assert merged.is_valid is False
        assert merged.errors == ("b failed",)

    def test_merge_two_invalid_concatenates_errors(self) -> None:
        a = SafetyValidation.failure("a1")
        b = SafetyValidation.failure("b1", "b2")
        merged = a.merge(b)
        assert merged.is_valid is False
        assert merged.errors == ("a1", "b1", "b2")


class TestSignalDecision:
    def test_signal_key_is_derived_from_fields(self) -> None:
        decision = SignalDecision(
            action=SignalAction.HOLD,
            symbol="BTC",
            interval="1h",
            candle_timestamp=1700000000,
            strategy_hash="abc123",
        )
        assert decision.signal_key == "BTC:1h:1700000000:abc123"

    def test_hold_produces_valid_key(self) -> None:
        decision = SignalDecision(action=SignalAction.HOLD)
        assert decision.signal_key == "::0:"

    def test_entry_and_exit_actions_are_distinct(self) -> None:
        assert SignalAction.LONG_ENTRY != SignalAction.LONG_EXIT
        assert SignalAction.SHORT_ENTRY != SignalAction.SHORT_EXIT


class TestDomainEnums:
    def test_order_side_values(self) -> None:
        assert OrderSide.BUY == "buy"
        assert OrderSide.SELL == "sell"

    def test_order_type_values(self) -> None:
        assert OrderType.MARKET == "market"
        assert OrderType.LIMIT == "limit"

    def test_position_direction_values(self) -> None:
        assert PositionDirection.LONG == "long"
        assert PositionDirection.SHORT == "short"
        assert PositionDirection.FLAT == "flat"

    def test_signal_action_values(self) -> None:
        assert SignalAction.HOLD == "hold"
        assert SignalAction.LONG_ENTRY == "long_entry"
