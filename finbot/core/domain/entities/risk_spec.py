"""RiskSpec entity for JSON strategy risk settings."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskSpec:
    """Structured risk settings for a JSON strategy."""

    stop_loss_type: str = "none"
    """Stop-loss model type: none, atr, or fixed_pct for MVP."""

    stop_indicator: str = ""
    """Concrete bar column used by the stop model, e.g. atr."""

    stop_multiplier: float = 0.0
    """Multiplier for ATR-based stops."""

    stop_pct: float = 0.0
    """Percentage distance for fixed percentage stops."""

    take_profit_type: str = "none"
    """Take-profit model type: none, atr, fixed_pct, or risk_reward."""

    take_profit_indicator: str = ""
    """Concrete bar column used by ATR take-profit models."""

    take_profit_multiplier: float = 0.0
    """Multiplier for ATR-based take-profit targets."""

    take_profit_pct: float = 0.0
    """Percentage distance for fixed percentage take-profit targets."""

    risk_reward_ratio: float = 0.0
    """Reward/risk ratio for risk_reward targets."""
