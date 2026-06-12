"""Tests for the JSON risk price calculator."""

from finbot.core.domain.entities.risk_spec import RiskSpec
from finbot.infrastructure.strategy.json_risk_price_calculator import (
    JsonRiskPriceCalculator,
)


def _calc() -> JsonRiskPriceCalculator:
    return JsonRiskPriceCalculator()


def _bar(**fields: object) -> dict:
    return dict(fields)


class TestJsonRiskPriceCalculator:
    def test_long_atr_stop_loss(self) -> None:
        calc = _calc()
        risk = RiskSpec(
            stop_loss_type="atr",
            stop_indicator="atr",
            stop_multiplier=3.5,
            take_profit_type="risk_reward",
            risk_reward_ratio=1.5,
        )
        stop, target = calc.calculate(risk, _bar(close=100.0, atr=2.0), "long")
        # Stop: 100 - (2.0 * 3.5) = 93.0
        assert stop == 93.0
        # Target: 100 + (100 - 93) * 1.5 = 110.5
        assert target == 110.5

    def test_short_atr_stop_loss(self) -> None:
        calc = _calc()
        risk = RiskSpec(
            stop_loss_type="atr",
            stop_indicator="atr",
            stop_multiplier=2.0,
            take_profit_type="risk_reward",
            risk_reward_ratio=1.0,
        )
        stop, target = calc.calculate(risk, _bar(close=50.0, atr=1.5), "short")
        # Stop: 50 + (1.5 * 2.0) = 53.0
        assert stop == 53.0
        # Target: 50 - (53 - 50) * 1.0 = 47.0
        assert target == 47.0

    def test_risk_reward_take_profit_for_long(self) -> None:
        calc = _calc()
        risk = RiskSpec(
            stop_loss_type="atr",
            stop_indicator="atr",
            stop_multiplier=2.0,
            take_profit_type="risk_reward",
            risk_reward_ratio=2.0,
        )
        stop, target = calc.calculate(risk, _bar(close=200.0, atr=5.0), "long")
        # Stop: 200 - (5*2) = 190
        # Distance: 200-190 = 10
        # Target: 200 + 10*2 = 220
        assert stop == 190.0
        assert target == 220.0

    def test_risk_reward_take_profit_for_short(self) -> None:
        calc = _calc()
        risk = RiskSpec(
            stop_loss_type="atr",
            stop_indicator="atr",
            stop_multiplier=2.0,
            take_profit_type="risk_reward",
            risk_reward_ratio=2.0,
        )
        stop, target = calc.calculate(risk, _bar(close=200.0, atr=5.0), "short")
        # Stop: 200 + (5*2) = 210
        # Distance: 210-200 = 10
        # Target: 200 - 10*2 = 180
        assert stop == 210.0
        assert target == 180.0

    def test_missing_atr_field_returns_zeroes(self) -> None:
        calc = _calc()
        risk = RiskSpec(
            stop_loss_type="atr",
            stop_indicator="atr",
            stop_multiplier=3.5,
        )
        stop, target = calc.calculate(risk, _bar(close=100.0), "long")
        assert stop == 0.0
        assert target == 0.0

    def test_none_risk_returns_zeroes(self) -> None:
        calc = _calc()
        stop, target = calc.calculate(None, _bar(close=100.0), "long")
        assert stop == 0.0
        assert target == 0.0

    def test_zero_multiplier_returns_zeroes(self) -> None:
        calc = _calc()
        risk = RiskSpec(
            stop_loss_type="atr",
            stop_indicator="atr",
            stop_multiplier=0.0,
        )
        stop, target = calc.calculate(risk, _bar(close=100.0, atr=2.0), "long")
        assert stop == 0.0
        assert target == 0.0

    def test_fixed_pct_stop_for_long(self) -> None:
        calc = _calc()
        risk = RiskSpec(
            stop_loss_type="fixed_pct",
            stop_pct=0.05,
        )
        stop, target = calc.calculate(risk, _bar(close=200.0), "long")
        # Stop: 200 * (1 - 0.05) = 190
        assert stop == 190.0
        assert target == 0.0

    def test_fixed_pct_stop_for_short(self) -> None:
        calc = _calc()
        risk = RiskSpec(
            stop_loss_type="fixed_pct",
            stop_pct=0.03,
        )
        stop, target = calc.calculate(risk, _bar(close=100.0), "short")
        # Stop: 100 * (1 + 0.03) = 103
        assert stop == 103.0
