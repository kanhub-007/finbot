"""JsonRiskPriceCalculator — calculate risk prices for JSON strategies."""

from finbot.core.domain.entities.risk_spec import RiskSpec
from finbot.core.domain.interfaces.risk_price_calculator import RiskPriceCalculator


class JsonRiskPriceCalculator(RiskPriceCalculator):
    """Calculate stop-loss and take-profit prices from RiskSpec settings."""

    def calculate(
        self,
        risk: RiskSpec | None,
        bar: dict,
        side: str,
    ) -> tuple[float, float]:
        """Return rounded stop and target prices for an entry signal."""
        if risk is None:
            return 0.0, 0.0
        try:
            close = float(bar.get("close", 0) or 0)
        except (TypeError, ValueError):
            return 0.0, 0.0
        if close <= 0:
            return 0.0, 0.0
        stop = _calculate_stop(risk, bar, close, side)
        target = _calculate_target(risk, bar, close, side, stop)
        return round(stop, 2), round(target, 2)


def _calculate_stop(risk: RiskSpec, bar: dict, close: float, side: str) -> float:
    handler = _STOP_HANDLERS.get(risk.stop_loss_type)
    return handler(risk, bar, close, side) if handler else 0.0


def _calculate_target(
    risk: RiskSpec,
    bar: dict,
    close: float,
    side: str,
    stop: float,
) -> float:
    handler = _TARGET_HANDLERS.get(risk.take_profit_type)
    return handler(risk, bar, close, side, stop) if handler else 0.0


# ---------------------------------------------------------------------------
# Stop-loss handlers
# ---------------------------------------------------------------------------


def _stop_atr(risk: RiskSpec, bar: dict, close: float, side: str) -> float:
    try:
        atr = float(bar.get(risk.stop_indicator, 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    if atr <= 0 or risk.stop_multiplier <= 0:
        return 0.0
    distance = atr * risk.stop_multiplier
    return close - distance if side == "long" else close + distance


def _stop_fixed_pct(risk: RiskSpec, _bar: dict, close: float, side: str) -> float:
    if risk.stop_pct <= 0:
        return 0.0
    if side == "long":
        return close * (1 - risk.stop_pct)
    return close * (1 + risk.stop_pct)


def _stop_none(*_args) -> float:
    # Accepts any arguments so the handler registry never raises TypeError
    # for an unrecognized key. Returns 0.0 (no stop) for graceful degradation.
    return 0.0


# ---------------------------------------------------------------------------
# Take-profit handlers
# ---------------------------------------------------------------------------


def _target_atr(
    risk: RiskSpec, bar: dict, close: float, side: str, _stop: float
) -> float:
    try:
        atr = float(bar.get(risk.take_profit_indicator, 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    if atr <= 0 or risk.take_profit_multiplier <= 0:
        return 0.0
    distance = atr * risk.take_profit_multiplier
    return close + distance if side == "long" else close - distance


def _target_fixed_pct(
    risk: RiskSpec, _bar: dict, close: float, side: str, _stop: float
) -> float:
    if risk.take_profit_pct <= 0:
        return 0.0
    return (
        close * (1 + risk.take_profit_pct)
        if side == "long"
        else close * (1 - risk.take_profit_pct)
    )


def _target_risk_reward(
    risk: RiskSpec, _bar: dict, close: float, side: str, stop: float
) -> float:
    if stop <= 0 or risk.risk_reward_ratio <= 0:
        return 0.0
    distance = abs(close - stop) * risk.risk_reward_ratio
    return close + distance if side == "long" else close - distance


def _target_none(*_args) -> float:
    # Same graceful-degradation pattern as _stop_none.
    return 0.0


_STOP_HANDLERS = {
    "atr": _stop_atr,
    "fixed_pct": _stop_fixed_pct,
    "none": _stop_none,
}

_TARGET_HANDLERS = {
    "atr": _target_atr,
    "fixed_pct": _target_fixed_pct,
    "risk_reward": _target_risk_reward,
    "none": _target_none,
}
